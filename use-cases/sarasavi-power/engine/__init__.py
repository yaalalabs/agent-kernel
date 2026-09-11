"""Sarasavi Power — deterministic, framework-agnostic domain engine.

Correctness bedrock: tariff + consumption math with zero LLM and zero Agent Kernel
dependencies. Agent Kernel tool wrappers import from here; nothing here imports them.
"""

from .consumption import Appliance, appliance_kwh, estimate_total, load_appliances
from .tariff import (
    TariffTable,
    boundary_opportunities,
    compute_bill,
    compute_tou_bill,
    load_tariff,
    simulate_reduction,
    sscl_levy,
    units_for_bill,
)

__all__ = [
    "TariffTable",
    "load_tariff",
    "compute_bill",
    "compute_tou_bill",
    "sscl_levy",
    "units_for_bill",
    "boundary_opportunities",
    "simulate_reduction",
    "Appliance",
    "load_appliances",
    "appliance_kwh",
    "estimate_total",
]
