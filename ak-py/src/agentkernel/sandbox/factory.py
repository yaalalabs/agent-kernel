"""Factories resolving sandbox providers and broker flavors from ``AKConfig``.

Both follow the guardrail/multimodal precedent: config-keyed, lazy per-backend imports, an
open dotted-path escape hatch, and a clear error when a selected backend's optional extra is
not installed. Neither imports any concrete provider or broker at module load — a backend is
imported only when a profile/flavor selects it.
"""

from typing import Any, ClassVar, Optional

from pydantic import BaseModel, ConfigDict

from ..core.config import AKConfig
from ..core.util.factory import require_extra, resolve_dotted
from .base import SandboxProvider
from .errors import SandboxConfigError

# Landed built-in provider short names (each an if/elif real-import branch in _build).
# A new built-in adds its branch and its name here; anything else must be a dotted path.
_BUILTIN_PROVIDER_NAMES = ["local_subprocess", "docker"]

# short name -> dotted path of the built-in broker flavor. Brokers stay on the
# resolve_dotted-over-map form (not if/elif real imports) because flavors living outside
# core sandbox (the AWS 'sqs' flavor under deployment/aws/) must remain dotted paths.
_BUILTIN_BROKERS: dict[str, str] = {
    "embedded": "agentkernel.sandbox.broker.embedded.EmbeddedBroker",
    "thread": "agentkernel.sandbox.broker.thread.ThreadBroker",
}


class _DottedParams(BaseModel):
    """Permissive config passed to a dotted-path provider that declares no ``config_model``."""

    model_config = ConfigDict(extra="allow")


class SandboxProviderFactory:
    """Resolves and caches one ``SandboxProvider`` per (profile, type)."""

    _cache: ClassVar[dict[tuple[str, str], SandboxProvider]] = {}

    @classmethod
    def get(cls, profile_name: Optional[str] = None) -> Optional[SandboxProvider]:
        """Return the provider for ``profile_name`` (default profile when omitted).

        Returns ``None`` when the capability is disabled; raises ``SandboxConfigError`` for
        an unknown profile. Instances are cached per (profile, type) and built lazily.
        """
        config = AKConfig.get().sandbox
        if not config.enabled:
            return None  # capability absent — callers treat None as "no sandbox"
        profile_name = profile_name or config.default_profile
        profile = config.profiles.get(profile_name)
        if profile is None:
            raise SandboxConfigError(f"unknown sandbox profile '{profile_name}'; configured profiles: {sorted(config.profiles)}")

        cache_key = (profile_name, profile.type)
        cached = cls._cache.get(cache_key)
        if cached is not None:
            return cached
        provider = cls._build(profile_name, profile)
        cls._cache[cache_key] = provider
        return provider

    @classmethod
    def _build(cls, profile_name: str, profile: Any) -> SandboxProvider:
        """Construct the provider for a profile: built-ins are ``if/elif`` real-import
        branches (#541 house shape); anything else is treated as a dotted path to a
        ``SandboxProvider`` subclass (BYO)."""
        type_name = profile.type

        if type_name == "local_subprocess":
            config_block = cls._require_block(profile_name, profile, type_name)
            from .providers.local_subprocess import LocalSubprocessSandboxProvider

            return LocalSubprocessSandboxProvider(config_block)

        if type_name == "docker":
            config_block = cls._require_block(profile_name, profile, type_name)
            with require_extra("sandbox-docker", "sandbox provider 'docker'"):
                from .providers.docker import DockerSandboxProvider

            return DockerSandboxProvider(config_block)

        if "." not in type_name:
            raise SandboxConfigError(
                f"unknown sandbox provider type '{type_name}'; expected one of {_BUILTIN_PROVIDER_NAMES} "
                "or a dotted path to a SandboxProvider subclass"
            )

        # Bring-your-own: a dotted path to a SandboxProvider subclass (keeps SandboxConfigError).
        provider_cls = resolve_dotted(type_name, base=SandboxProvider, error=SandboxConfigError)
        # A dotted-path provider may declare `config_model` (a BaseModel subclass) to validate
        # the profile's `params`; otherwise params pass through a permissive model.
        config_model = getattr(provider_cls, "config_model", None)
        if isinstance(config_model, type) and issubclass(config_model, BaseModel):
            config = config_model.model_validate(profile.params)
        else:
            config = _DottedParams(**profile.params)
        return provider_cls(config)

    @staticmethod
    def _require_block(profile_name: str, profile: Any, type_name: str) -> Any:
        """Return the profile's ``<type>`` config block; a missing block for a built-in is a
        ``SandboxConfigError`` (the multimodal-storage precedent)."""
        block = getattr(profile, type_name, None)
        if block is None:
            raise SandboxConfigError(
                f"sandbox profile '{profile_name}' selects built-in provider '{type_name}' but its '{type_name}' config block is missing"
            )
        return block

    @classmethod
    def _reset(cls) -> None:
        """Drop the cached providers so the next get() rebuilds. Intended for testing."""
        cls._cache = {}


class SandboxBrokerFactory:
    """Resolves the configured broker flavor to a ``SandboxBroker`` instance."""

    @classmethod
    def get(cls):
        """Build the broker for the configured ``sandbox.broker.flavor``.

        Built-in short names map to their dotted paths; a dotted path is treated as a
        ``SandboxBroker`` subclass (BYO); an unknown non-dotted flavor fails loud, naming the
        value and the built-ins (#541 error shape — matching the provider path). The broker is
        constructed with the ``sandbox.broker`` config block.
        """
        from .broker.base import SandboxBroker  # local import: avoid eager broker import at module load

        config = AKConfig.get().sandbox
        flavor = config.broker.flavor
        if flavor not in _BUILTIN_BROKERS and "." not in flavor:
            raise SandboxConfigError(
                f"unknown sandbox broker flavor '{flavor}'; expected one of {sorted(_BUILTIN_BROKERS)} "
                "or a dotted path to a SandboxBroker subclass"
            )
        dotted = _BUILTIN_BROKERS.get(flavor, flavor)  # short name -> dotted path, else treat as dotted path
        broker_cls = resolve_dotted(dotted, base=SandboxBroker, error=SandboxConfigError)
        return broker_cls(config.broker)
