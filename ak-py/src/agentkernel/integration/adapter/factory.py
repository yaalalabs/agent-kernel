import threading
from typing import Dict

from ...core.config import AKConfig
from ...core.util.factory import AKConfigError, require_extra, resolve_dotted
from .base import OutboundAdapter


class IntegrationAdapterFactory:
    """Resolves an ``integration`` attribute value to the adapter that delivers its replies.

    Only the outbound half is resolved by name: the application constructs the inbound adapter
    itself and hands it to a host, whereas the Response Handler holds nothing but the string the
    producer stamped on the message.

    A built-in short name resolves to that platform's adapter, unless its config block names a
    dotted path in ``outbound_adapter``. Any other value is treated as a dotted path to an
    :class:`OutboundAdapter` subclass — the bring-your-own path for a platform that is not one
    of the seven built-ins.
    """

    _BUILTIN_NAMES = ("slack", "whatsapp", "messenger", "instagram", "telegram", "teams", "gmail")
    _cache: Dict[str, OutboundAdapter] = {}
    _lock = threading.Lock()

    @classmethod
    def create_outbound(cls, name: str) -> OutboundAdapter:
        """Return the outbound adapter for an ``integration`` attribute value.

        :param name: A built-in short name, or a dotted path to an OutboundAdapter subclass.
        :return: The adapter instance (shared; adapters are stateless per message).
        :raises AKConfigError: If the name is neither a built-in nor a resolvable dotted path.
        :raises ImportError: If a built-in's optional dependency is not installed.
        """
        with cls._lock:
            adapter = cls._cache.get(name)
            if adapter is None:
                adapter = cls._build(name)
                cls._cache[name] = adapter
            return adapter

    @classmethod
    def reset(cls) -> None:
        """Drop the instance cache. For tests that swap configuration between cases."""
        with cls._lock:
            cls._cache.clear()

    @classmethod
    def _build(cls, name: str) -> OutboundAdapter:
        if name in cls._BUILTIN_NAMES:
            override = getattr(getattr(AKConfig.get(), name), "outbound_adapter", "")
            if override:
                return resolve_dotted(override, base=OutboundAdapter)()
            return cls._builtin(name)
        if "." not in name:
            raise AKConfigError(
                f"unknown integration adapter '{name}'; expected one of {list(cls._BUILTIN_NAMES)} " "or a dotted path to an OutboundAdapter subclass"
            )
        return resolve_dotted(name, base=OutboundAdapter)()

    @classmethod
    def _builtin(cls, name: str) -> OutboundAdapter:
        feature = f"integration '{name}'"
        if name == "slack":
            with require_extra("slack", feature):
                from ..slack.adapter import SlackOutboundAdapter

            return SlackOutboundAdapter()
        if name == "whatsapp":
            with require_extra("whatsapp", feature):
                from ..whatsapp.adapter import WhatsAppOutboundAdapter

            return WhatsAppOutboundAdapter()
        if name == "messenger":
            with require_extra("messenger", feature):
                from ..messenger.adapter import MessengerOutboundAdapter

            return MessengerOutboundAdapter()
        if name == "instagram":
            with require_extra("instagram", feature):
                from ..instagram.adapter import InstagramOutboundAdapter

            return InstagramOutboundAdapter()
        if name == "telegram":
            with require_extra("telegram", feature):
                from ..telegram.adapter import TelegramOutboundAdapter

            return TelegramOutboundAdapter()
        if name == "teams":
            with require_extra("teams", feature):
                from ..teams.adapter import TeamsOutboundAdapter

            return TeamsOutboundAdapter()
        if name == "gmail":
            with require_extra("gmail", feature):
                from ..gmail.adapter import GmailOutboundAdapter

            return GmailOutboundAdapter()
        raise AKConfigError(f"integration adapter '{name}' is listed as a built-in but has no implementation wired up")
