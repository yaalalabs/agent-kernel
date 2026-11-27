"""Token exchange (#603): how the inbound credential of a run becomes a token for one downstream audience.

No exchange flow ships in this change (design section 3.1, Q19): ``passthrough`` forwards the inbound token as it
came, for development, so the seam is exercised end to end. A deployment that needs an exchange brings one by
dotted path; the names of the flows a later release will ship are reserved and refused.
"""

import base64
import binascii
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from ...core.model import Principal
from ...core.util.factory import AKConfigError, resolve_dotted

if TYPE_CHECKING:
    from ...core.config import _CredentialsConfig, _ExchangerConfig


class IssuedToken(BaseModel):
    """A token an exchanger issued for one audience. Its ``repr`` leaves the token out."""

    model_config = ConfigDict(frozen=True)

    access_token: str = Field(repr=False, description="The token, sent to the audience as its bearer credential")
    expires_at: float = Field(description="When the token expires, in UNIX epoch seconds")
    token_type: str = Field(default="Bearer", description="How the token is presented")


class TokenExchanger(ABC):
    """Turns a run's inbound credential into a token for one audience.

    Built from its ``identity.credentials.exchangers[]`` entry: ``audience`` is what the broker matches a request
    against, exactly, and ``scopes`` what it asks for when a tool names none. A bring-your-own exchanger reads
    settings of its own from ``config.model_extra``. An exchanger never logs a token.
    """

    cacheable: ClassVar[bool] = True
    """Whether the broker may cache what this exchanger issues. False for a token that is the inbound one."""

    def __init__(self, config: "_ExchangerConfig"):
        """
        :param config: The exchanger's entry in ``identity.credentials.exchangers``.
        """
        self.audience = config.audience
        self.scopes = list(config.scopes)

    @abstractmethod
    async def exchange(self, inbound: str, audience: str, scopes: list[str], actor: Principal | None) -> IssuedToken:
        """
        :param inbound: The run's inbound credential.
        :param audience: The audience the token is for.
        :param scopes: The scopes asked for.
        :param actor: The agent acting for the user, for an exchange that records who acts (RFC 8693 ``actor_token``).
        :return: The issued token.
        """


class PassthroughTokenExchanger(TokenExchanger):
    """Forwards the inbound token unchanged. For development only, and says so when it is built.

    The token is reported to expire with the inbound credential: at its ``exp`` claim when one can be read, and
    never later than ``inbound_ttl`` from now. It is never cached: the token is the user's own, and a copy in the
    store would outlive the run it was kept for.
    """

    cacheable: ClassVar[bool] = False
    _log = logging.getLogger("ak.identity.credential.exchange")

    def __init__(self, config: "_ExchangerConfig", inbound_ttl: int):
        """
        :param config: The exchanger's entry.
        :param inbound_ttl: ``identity.credentials.inbound_ttl``.
        """
        super().__init__(config)
        self._inbound_ttl = inbound_ttl
        self._log.warning(f"passthrough exchanger configured for {config.audience}: the inbound token is forwarded as-is; dev only")

    async def exchange(self, inbound: str, audience: str, scopes: list[str], actor: Principal | None) -> IssuedToken:
        expires_at = time.time() + self._inbound_ttl
        exp = self._expiry(inbound)
        return IssuedToken(access_token=inbound, expires_at=min(exp, expires_at) if exp is not None else expires_at)

    @staticmethod
    def _expiry(token: str) -> float | None:
        """
        Reads the ``exp`` claim of a JWT without verifying it: the identity provider verified the token when the
        run's request was authenticated, and nothing here trusts the claim beyond capping how long a copy is kept.

        :param token: The inbound token.
        :return: The expiry in epoch seconds, or None when the token is not a JWT or carries no numeric ``exp``.
        """
        parts = token.split(".")
        if len(parts) != 3:
            return None
        try:
            payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        except (binascii.Error, ValueError):
            return None
        exp = payload.get("exp") if isinstance(payload, dict) else None
        return float(exp) if isinstance(exp, (int, float)) and not isinstance(exp, bool) else None


class TokenExchangerFactory:
    """Builds the exchangers ``identity.credentials.exchangers`` lists."""

    RESERVED: ClassVar[tuple[str, ...]] = ("rfc8693", "entra_obo", "id_jag")
    """Exchange flows a later release will ship; refused now, so a configuration written for one fails loudly."""

    @staticmethod
    def create(config: "_ExchangerConfig", inbound_ttl: int) -> TokenExchanger:
        """
        :param config: One entry of ``identity.credentials.exchangers``. ``type`` is ``passthrough``, matched whatever
            its case, or a dotted path to a ``TokenExchanger`` subclass, built with the entry.
        :param inbound_ttl: ``identity.credentials.inbound_ttl``.
        :return: The exchanger.
        :raises AKConfigError: If the type is reserved, unknown, or a dotted path that does not resolve to one.
        """
        key = config.type.lower()
        if key == "passthrough":
            return PassthroughTokenExchanger(config, inbound_ttl)
        if key in TokenExchangerFactory.RESERVED:
            raise AKConfigError(f"identity.credentials.exchangers[].type: {key} is not shipped yet; use a dotted path")
        if "." not in config.type:
            raise AKConfigError(f"unknown token exchanger type '{config.type}'; expected passthrough or a dotted path to a TokenExchanger subclass")
        return resolve_dotted(config.type, base=TokenExchanger)(config)

    @staticmethod
    def create_all(config: "_CredentialsConfig") -> dict[str, TokenExchanger]:
        """
        :param config: The ``identity.credentials`` block.
        :return: Each exchanger by the audience it serves.
        :raises AKConfigError: If an entry cannot be built, or two entries serve one audience.
        """
        exchangers: dict[str, TokenExchanger] = {}
        for entry in config.exchangers:
            if entry.audience in exchangers:
                raise AKConfigError(f"identity.credentials.exchangers lists two exchangers for audience '{entry.audience}'")
            exchangers[entry.audience] = TokenExchangerFactory.create(entry, config.inbound_ttl)
        return exchangers
