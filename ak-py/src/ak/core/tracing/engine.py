from typing import Optional, Tuple
import logging
from pydantic import BaseModel

from ..config import AKConfig
from .enums_and_mappings import PROVIDER_TO_TRACER_CLASS, TracingProviderEnum
from .tracers import Tracer

_log = logging.getLogger("ak.core.tracing.engine")


def _resolve_provider_for_framework(framework: str) -> Tuple[Optional[TracingProviderEnum], Optional[Tuple[str, Optional[BaseModel]]]]: 
    """Resolve provider and payload (app_name, variables) for a given agent framework.

    Returns (None, None) when tracing is disabled or framework not configured.
    """
    tracing_cfg = AKConfig.get().tracing
    if not tracing_cfg:
        _log.debug("Tracing config is missing; returning (None, None)")
        return None, None
    if not tracing_cfg.enabled:
        _log.debug("Tracing is disabled; returning (None, None)")
        return None, None

    original_framework = framework
    framework = (framework or "").lower().strip()
    _log.debug(f"Resolving provider for framework '{original_framework}' normalized to '{framework}'")

    fw_cfg = (tracing_cfg.frameworks or {}).get(framework)
    if not fw_cfg:
        _log.debug(f"No tracing configuration found for framework '{framework}'")
        return None, None

    app_name = fw_cfg.name or tracing_cfg.name
    variables = getattr(fw_cfg, "variables", None)
    provider = TracingProviderEnum(fw_cfg.provider)
    vars_repr = "None" if variables is None else variables.__class__.__name__ # getting the class name
    _log.debug(f"Resolved tracing provider '{provider.value}' with app_name '{app_name}' and variables type {vars_repr}")
    return provider, (app_name, variables)


def get_tracer(framework: str) -> Optional[Tracer]:
    """Create a tracer instance for the specified agent framework using configuration.

    Returns None when tracing is not enabled. Raises ValueError when tracing is enabled
    but not configured properly, or when the provider is unsupported.
    """
    tracing_cfg = AKConfig.get().tracing
    enabled = bool(tracing_cfg and tracing_cfg.enabled)

    _log.debug(f"get_tracer called for framework '{framework}' (enabled={enabled})")

    provider_enum, payload = _resolve_provider_for_framework(framework)
    if not provider_enum or not payload:
        if not enabled:
            _log.debug("Tracing not enabled; returning None from get_tracer")
            return None
        normalized = (framework or "").lower().strip()
        raise ValueError(
            f"Tracing is enabled but not properly configured for framework '{normalized}'. "
            f"Please configure AK.tracing.frameworks['{normalized}'] with a supported provider."
        )

    app_name, variables = payload

    # Use the mapping to resolve the proper tracer class based on provider, Make sure the mapping is up to date!
    provider_key = provider_enum.value if hasattr(provider_enum, "value") else str(provider_enum).lower()
    tracer_cls = PROVIDER_TO_TRACER_CLASS.get(provider_key)
    if not tracer_cls:
        supported = ", ".join(sorted(PROVIDER_TO_TRACER_CLASS.keys())) or "none"
        raise ValueError(f"Unsupported tracing provider '{provider_key}'. Supported providers: {supported}.")

    _log.debug(f"Creating tracer for provider '{provider_key}' with app_name '{app_name}'")
    return tracer_cls(app_name=app_name, variables=variables)