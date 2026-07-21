"""Factories resolving sandbox providers and broker flavors from ``AKConfig``.

Both follow the guardrail/multimodal precedent: config-keyed, lazy per-backend imports, an
open dotted-path escape hatch, and a clear error when a selected backend's optional extra is
not installed. Neither imports any concrete provider or broker at module load — a backend is
imported only when a profile/flavor selects it.
"""

import importlib
import logging
from typing import Any, ClassVar, Optional

from pydantic import BaseModel, ConfigDict

from ..core.config import AKConfig
from .base import SandboxProvider
from .errors import SandboxConfigError

logger = logging.getLogger("ak.sandbox")

# short name -> dotted path of the built-in provider class (imported lazily on selection)
_BUILTIN_PROVIDERS: dict[str, str] = {
    "local_subprocess": "agentkernel.sandbox.providers.local_subprocess.LocalSubprocessSandboxProvider",
    "docker": "agentkernel.sandbox.providers.docker.DockerSandboxProvider",
    "e2b": "agentkernel.sandbox.providers.e2b.E2BSandboxProvider",
    "daytona": "agentkernel.sandbox.providers.daytona.DaytonaSandboxProvider",
    "bedrock_agentcore": "agentkernel.sandbox.providers.bedrock_agentcore.BedrockAgentCoreSandboxProvider",
    "kubernetes": "agentkernel.sandbox.providers.kubernetes.KubernetesSandboxProvider",
    "ec2_ssm": "agentkernel.sandbox.providers.ec2_ssm.EC2SSMSandboxProvider",
}

# short name -> pip extra that ships its SDK (None = stdlib only); used to build the
# remediation message when the import fails.
_BUILTIN_EXTRAS: dict[str, Optional[str]] = {
    "local_subprocess": None,
    "docker": "sandbox-docker",
    "e2b": "e2b",
    "daytona": "daytona",
    "bedrock_agentcore": "aws",
    "kubernetes": "kubernetes",
    "ec2_ssm": "aws",
}

# short name -> dotted path of the built-in broker flavor (imported lazily on selection)
_BUILTIN_BROKERS: dict[str, str] = {
    "embedded": "agentkernel.sandbox.broker.embedded.EmbeddedBroker",
    "thread": "agentkernel.sandbox.broker.thread.ThreadBroker",
    "sqs": "agentkernel.deployment.aws.sandbox.sqs_broker.SQSSandboxBroker",
}


class _DottedParams(BaseModel):
    """Permissive config passed to a dotted-path provider that declares no ``config_model``."""

    model_config = ConfigDict(extra="allow")


def _import_dotted(path: str) -> Any:
    module_path, _, attr = path.rpartition(".")
    if not module_path:
        raise SandboxConfigError(f"'{path}' is not a dotted path to a class")
    module = importlib.import_module(module_path)
    return getattr(module, attr)


class SandboxProviderFactory:
    """Resolves and caches one ``SandboxProvider`` per (profile, type)."""

    _cache: ClassVar[dict[tuple[str, str], SandboxProvider]] = {}

    @classmethod
    def get(cls, profile_name: Optional[str] = None) -> Optional[SandboxProvider]:
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
        type_name = profile.type
        if type_name in _BUILTIN_PROVIDERS:
            try:
                provider_cls = _import_dotted(_BUILTIN_PROVIDERS[type_name])
            except ImportError as exc:
                extra = _BUILTIN_EXTRAS.get(type_name)
                if extra:
                    raise ImportError(f"Sandbox provider '{type_name}' requires the '{extra}' extra: pip install \"agentkernel[{extra}]\"") from exc
                raise
            config_block = getattr(profile, type_name, None)
            if config_block is None:
                raise SandboxConfigError(
                    f"sandbox profile '{profile_name}' selects built-in provider '{type_name}' but its '{type_name}' config block is missing"
                )
            return provider_cls(config_block)

        # dotted path
        try:
            provider_cls = _import_dotted(type_name)
        except (ImportError, AttributeError, SandboxConfigError) as exc:
            raise SandboxConfigError(f"could not import sandbox provider '{type_name}': {exc}") from exc
        if not (isinstance(provider_cls, type) and issubclass(provider_cls, SandboxProvider)):
            raise SandboxConfigError(f"sandbox provider '{type_name}' is not a SandboxProvider subclass")
        # A dotted-path provider may declare `config_model` (a BaseModel subclass) to validate
        # the profile's `params`; otherwise params pass through a permissive model.
        config_model = getattr(provider_cls, "config_model", None)
        if isinstance(config_model, type) and issubclass(config_model, BaseModel):
            config = config_model.model_validate(profile.params)
        else:
            config = _DottedParams(**profile.params)
        return provider_cls(config)

    @classmethod
    def _reset(cls) -> None:
        """Drop the cached providers so the next get() rebuilds. Intended for testing."""
        cls._cache = {}


class SandboxBrokerFactory:
    """Resolves the configured broker flavor to a ``SandboxBroker`` instance."""

    @classmethod
    def get(cls):
        from .broker.base import SandboxBroker  # local import: avoid eager broker import at module load

        config = AKConfig.get().sandbox
        flavor = config.broker.flavor
        dotted = _BUILTIN_BROKERS.get(flavor, flavor)  # short name -> dotted path, else treat as dotted path
        try:
            broker_cls = _import_dotted(dotted)
        except (ImportError, AttributeError, SandboxConfigError) as exc:
            raise SandboxConfigError(f"could not import sandbox broker flavor '{flavor}': {exc}") from exc
        if not (isinstance(broker_cls, type) and issubclass(broker_cls, SandboxBroker)):
            raise SandboxConfigError(f"sandbox broker '{flavor}' is not a SandboxBroker subclass")
        return broker_cls(config.broker)
