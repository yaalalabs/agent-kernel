"""CredentialBroker (#603): what a tool asks for a token for a downstream audience, for the run it is in."""

import asyncio
import hashlib
import json
import time
from collections.abc import Callable, Mapping
from typing import Any, ClassVar, TypeVar

from ...core.model import Principal
from ..errors import CredentialError
from .exchange import IssuedToken, TokenExchanger
from .store import CredentialStore

T = TypeVar("T")


class CredentialBroker:
    """Hands a tool a token for an audience, from the inbound credential its run was started with.

    Built per run by ``ToolContext.credentials`` and holding nothing beyond its arguments. A run must still hold
    an inbound credential of its own (``principal.credential_ref``, read from the store before anything else):
    one started without (a scheduled occurrence), or whose credential is gone (a redelivered message, an expired
    connection), gets ``CredentialError``, never a token another run left in the cache. An issued token is cached
    in the credential store per principal, agent, audience, scopes and inbound credential (a digest of it), so a
    narrower token of the same user is never handed a broader one's token, and reused until 30 seconds before it
    expires; an exchanger that is not ``cacheable`` (``passthrough``) is never cached. Every failure is a
    ``CredentialError``, which a tool returns as its result; nothing here logs a token.
    """

    REFRESH_MARGIN: ClassVar[float] = 30.0
    """Seconds before its expiry a cached token is exchanged again."""

    def __init__(
        self,
        principal: Principal | None,
        store: CredentialStore | None,
        exchangers: Mapping[str, TokenExchanger],
        agent_id: str,
        unavailable: str | None = None,
    ):
        """
        :param principal: The run's principal, with the agent as its actor.
        :param store: The credential store; None when credentials are not configured, which every request reports.
        :param exchangers: The exchangers by the audience each serves.
        :param agent_id: The agent the run is of; tokens are cached per agent.
        :param unavailable: Why credentials cannot be had at all, reported instead of "not configured".
        """
        self._principal = principal
        self._store = store
        self._exchangers = exchangers
        self._agent_id = agent_id
        self._unavailable = unavailable

    @classmethod
    def for_run(cls, principal: Principal | None, agent_id: str) -> "CredentialBroker":
        """
        The broker of a run, over the process's credentials. Never raises: credentials that are not configured, or
        cannot be built, are reported by ``token_for``, so code that never asks for a token pays nothing.

        :param principal: The run's principal.
        :param agent_id: The agent the run is of.
        """
        try:
            from .manager import CredentialManager

            manager = CredentialManager.get()
        except Exception as error:
            return cls(principal, None, {}, agent_id, unavailable=f"credentials are unavailable: {type(error).__name__}")
        if manager is None:
            return cls(principal, None, {}, agent_id)
        return manager.broker(principal, agent_id)

    async def token_for(self, audience: str, scopes: list[str] | None = None) -> str:
        """
        :param audience: The downstream audience, matched exactly against the configured exchangers.
        :param scopes: The scopes to ask for; None asks for the exchanger's configured ones.
        :return: A token for the audience.
        :raises CredentialError: If credentials are not configured, the run has no inbound credential, no exchanger
            serves the audience, the exchange fails or the store cannot be reached.
        """
        if self._store is None:
            raise CredentialError(self._unavailable or "identity.credentials is not configured")
        principal = self._principal
        if principal is None or principal.credential_ref is None:
            raise CredentialError("no inbound credential for this run")
        exchanger = self._exchangers.get(audience)
        if exchanger is None:
            raise CredentialError(f"no exchanger configured for audience '{audience}'")
        wanted = list(scopes) if scopes is not None else list(exchanger.scopes)
        inbound = await self._stored(self._store.get, principal.credential_ref)
        if inbound is None:
            raise CredentialError("no inbound credential for this run")

        key = self._cache_key(audience, wanted, inbound)
        cached = await self._stored(self._store.get, key) if exchanger.cacheable else None
        if cached is not None:
            issued = IssuedToken.model_validate_json(cached)
            if issued.expires_at - self.REFRESH_MARGIN > time.time():
                return issued.access_token
        try:
            issued = await exchanger.exchange(inbound.decode(), audience, wanted, principal.actor)
        except CredentialError:
            raise
        except Exception as error:
            # Not chained into the message: an exchange error can quote the token it was handed.
            raise CredentialError(f"the token exchange for audience '{audience}' failed: {type(error).__name__}") from None
        if exchanger.cacheable and issued.expires_at > time.time():
            await self._stored(self._store.put, key, issued.model_dump_json().encode(), issued.expires_at)
        return issued.access_token

    def _cache_key(self, audience: str, scopes: list[str], inbound: bytes) -> str:
        """
        The store key of an issued token: a digest, so the key names no user, no audience and no token.

        :param audience: The audience.
        :param scopes: The scopes asked for, in any order.
        :param inbound: The run's inbound credential, so a token is reused only for the credential it was issued for.
        """
        principal = self._principal
        parts = [
            principal.subject if principal else None,
            principal.provider if principal else None,
            principal.namespace if principal else None,
            self._agent_id,
            audience,
            sorted(scopes),
            hashlib.sha256(inbound).hexdigest(),
        ]
        return "cred:issued:" + hashlib.sha256(json.dumps(parts).encode()).hexdigest()

    @staticmethod
    async def _stored(operation: Callable[..., T], *arguments: Any) -> T:
        """
        Runs one store operation off the event loop, a store that cannot be reached reported as a ``CredentialError``.

        :param operation: The store method.
        :param arguments: Its arguments.
        """
        try:
            return await asyncio.to_thread(operation, *arguments)
        except CredentialError:
            raise
        except Exception as error:
            raise CredentialError(f"the credential store could not be reached: {type(error).__name__}") from None
