"""CredentialManager (#603): the credentials capability of this process, and the lifecycle of a retained credential.

A surface that authenticates a request *retains* its credential: the token is kept, encrypted, in the credential
store under a fresh reference, and the principal carries the reference, never the token. Whoever ends the run
*releases* it: ``Runtime`` on the direct path and the agent runner on the queued one. A WebSocket connection or a
CLI session runs many requests on one credential, so it retains it *for the connection* (a ``conn:`` reference),
which a run's release leaves alone and the connection *forgets* when it ends.
"""

import asyncio
import logging
import threading
import time
import uuid
from collections.abc import Mapping
from typing import TYPE_CHECKING, ClassVar, Optional

from ...core.config import AKConfig
from ...core.model import Principal
from .broker import CredentialBroker
from .exchange import TokenExchanger, TokenExchangerFactory
from .store import CredentialStore, CredentialStoreFactory

if TYPE_CHECKING:
    from ...core.config import _CredentialsConfig


class CredentialManager:
    """The credential store and the exchangers of this process, built once from ``identity.credentials``."""

    CONNECTION_PREFIX: ClassVar[str] = "conn:"
    """The prefix of a reference kept for a connection rather than for one run."""

    _instance: ClassVar[Optional["CredentialManager"]] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()
    _log = logging.getLogger("ak.identity.credential.manager")

    def __init__(self, store: CredentialStore, exchangers: Mapping[str, TokenExchanger], inbound_ttl: int):
        """
        :param store: Where credentials are kept.
        :param exchangers: The exchangers by the audience each serves.
        :param inbound_ttl: Seconds a run's inbound credential is kept, at most.
        """
        self._store = store
        self._exchangers = dict(exchangers)
        self._inbound_ttl = inbound_ttl

    @property
    def store(self) -> CredentialStore:
        """Where credentials are kept."""
        return self._store

    @property
    def exchangers(self) -> Mapping[str, TokenExchanger]:
        """The exchangers by the audience each serves."""
        return self._exchangers

    @classmethod
    def from_config(cls, config: "_CredentialsConfig") -> "CredentialManager":
        """
        :param config: The ``identity.credentials`` block.
        :raises AKConfigError: If the store or an exchanger cannot be built from it.
        """
        return cls(CredentialStoreFactory.create(config), TokenExchangerFactory.create_all(config), config.inbound_ttl)

    @classmethod
    def get(cls) -> Optional["CredentialManager"]:
        """
        The process's manager, built on first use; None without an ``identity.credentials`` block, which every
        caller reads as "keep no credential".

        :raises AKConfigError: If the block cannot be built.
        """
        identity = getattr(AKConfig.get(), "identity", None)
        config = getattr(identity, "credentials", None) if identity is not None else None
        if config is None:
            return None
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls.from_config(config)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Drops the process's manager, so the next ``get`` builds it again (tests)."""
        with cls._lock:
            cls._instance = None

    async def retain(self, principal: Principal, credential: str, *, connection: bool = False) -> Principal:
        """
        Keeps a request's credential and returns its principal carrying the reference.

        A run's credential is kept until the token's ``exp`` claim, and no longer than ``inbound_ttl``; a
        connection's until the token's ``exp``, or ``inbound_ttl`` when it has none. Nothing is kept for the
        anonymous principal, an empty credential or a token that has already expired. A store that cannot be
        reached is logged and leaves the request without a credential rather than failing it.

        :param principal: The principal the credential authenticated.
        :param credential: The credential as it was presented.
        :param connection: Whether to keep it for a connection (a ``conn:`` reference) rather than one run.
        :return: The principal with ``credential_ref`` set, or as it came when nothing was kept.
        """
        if principal.is_anonymous or not credential:
            return principal
        now = time.time()
        exp = principal.claims.get("exp")
        exp = float(exp) if isinstance(exp, (int, float)) and not isinstance(exp, bool) else None
        if connection:
            expires_at = exp if exp is not None else now + self._inbound_ttl
        else:
            expires_at = min(exp, now + self._inbound_ttl) if exp is not None else now + self._inbound_ttl
        if expires_at <= now:
            return principal
        reference = (self.CONNECTION_PREFIX if connection else "") + uuid.uuid4().hex
        try:
            await asyncio.to_thread(self._store.put, reference, credential.encode(), expires_at)
        except Exception as error:
            self._log.error(f"The inbound credential of '{principal.subject}' could not be kept, so its run has none: {type(error).__name__}")
            return principal
        return principal.with_credential_ref(reference)

    def release(self, principal: Principal | None) -> None:
        """
        Deletes the credential a run was started with. A connection's reference, or none, is left alone. Never
        raises: a store that cannot be reached is logged, and the entry expires with its TTL.

        :param principal: The run's principal.
        """
        reference = principal.credential_ref if principal is not None else None
        if reference and not reference.startswith(self.CONNECTION_PREFIX):
            self._delete(reference)

    def forget(self, principal: Principal | None) -> None:
        """
        Deletes the credential a connection was opened with, when the connection ends. A run's reference, or none,
        is left alone. Never raises.

        :param principal: The connection's principal.
        """
        reference = principal.credential_ref if principal is not None else None
        if reference and reference.startswith(self.CONNECTION_PREFIX):
            self._delete(reference)

    @classmethod
    def release_for(cls, principal: Principal | None) -> None:
        """
        ``release`` on the process's manager, for code that holds none (``Runtime``, the agent runners). Never raises.

        :param principal: The run's principal.
        """
        if principal is None or not principal.credential_ref:
            return
        try:
            manager = cls.get()
        except Exception as error:
            cls._log.warning(f"The inbound credential of a run could not be deleted; it expires with its TTL: {type(error).__name__}")
            return
        if manager is not None:
            manager.release(principal)

    def broker(self, principal: Principal | None, agent_id: str) -> CredentialBroker:
        """
        :param principal: The run's principal.
        :param agent_id: The agent the run is of.
        :return: The run's broker.
        """
        return CredentialBroker(principal, self._store, self._exchangers, agent_id)

    def _delete(self, reference: str) -> None:
        try:
            self._store.delete(reference)
        except Exception as error:
            self._log.warning(f"An inbound credential could not be deleted; it expires with its TTL: {error!r}")
