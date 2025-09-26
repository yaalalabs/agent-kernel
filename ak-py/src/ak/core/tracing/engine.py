from typing import Optional, Tuple

from .enums_and_mappings import PROVIDER_TO_TRACER_CLASS
from ..config import AKConfig

from .tracers import Tracer
from .enums_and_mappings import TracingProviderEnum


def _resolve_provider_for_framework(framework: str) -> Tuple[Optional[TracingProviderEnum], Optional[Tuple[str, dict]]]:
    """Resolve provider and payload (app_name, variables) for a given agent framework.

    Returns (None, None) when tracing is disabled or framework not configured.
    """
    tracing_cfg = AKConfig.get().tracing
    if not tracing_cfg or not tracing_cfg.enabled:
        return None, None

    framework = (framework or "").lower().strip()

    fw_cfg = (tracing_cfg.frameworks or {}).get(framework)
    if not fw_cfg:
        return None, None

    app_name = fw_cfg.name or tracing_cfg.name
    variables = fw_cfg.variables.model_dump() if getattr(fw_cfg, "variables", None) else {}
    return TracingProviderEnum(fw_cfg.provider), (app_name, variables)


def get_tracer(framework: str) -> Optional[Tracer]:
    """Create a tracer instance for the specified agent framework using configuration.

    Raises ValueError when tracing is not configured or when the provider is unsupported.
    """
    provider_enum, payload = _resolve_provider_for_framework(framework)
    if not provider_enum or not payload:
        raise ValueError("Tracing is not configured for the requested framework or is disabled.")

    app_name, variables = payload

    # Use the mapping to resolve the proper tracer class based on provider
    provider_key = provider_enum.value if hasattr(provider_enum, "value") else str(provider_enum).lower()
    tracer_cls = PROVIDER_TO_TRACER_CLASS.get(provider_key)
    if not tracer_cls:
        supported = ", ".join(sorted(PROVIDER_TO_TRACER_CLASS.keys())) or "none"
        raise ValueError(f"Unsupported tracing provider '{provider_key}'. Supported providers: {supported}.")

    return tracer_cls(app_name=app_name, variables=variables)