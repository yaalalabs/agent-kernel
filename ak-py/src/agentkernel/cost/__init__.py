"""Cost management capability: usage capture through an LLM gateway, cost metering, and per-user budgets.

The capability is enabled by a ``cost`` block in config.yaml. Every export is lazy (PEP 562), so importing this
package loads nothing until a name is used: the gateway, client and handler modules pull in httpx, litellm and
FastAPI, which a process without the ``cost`` extra must not need. ``agentkernel.cost.testing`` (the contract
suites) imports pytest and is never re-exported here.
"""

import importlib
from typing import TYPE_CHECKING, Any

_LAZY_EXPORTS = {
    # model
    "ANONYMOUS_USER_ID": ".model",
    "AgentUsage": ".model",
    "Attribution": ".model",
    "BudgetDecision": ".model",
    "BudgetLimit": ".model",
    "BudgetPeriod": ".model",
    "GatewayCapabilities": ".model",
    "GatewayFilter": ".model",
    "ModelSpend": ".model",
    "ModelUsage": ".model",
    "SYSTEM_USER_ID": ".model",
    "SessionUsage": ".model",
    "SpendCursor": ".model",
    "SpendTotal": ".model",
    "UsageQuery": ".model",
    "UsageReport": ".model",
    "UsageResult": ".model",
    "UsageWindow": ".model",
    # attribution
    "AttributionContext": ".attribution",
    "Attributor": ".attribution",
    "AttributorFactory": ".attribution",
    "DefaultAttributor": ".attribution",
    # pricing
    "PassthroughPricingSource": ".pricing",
    "PricingSource": ".pricing",
    "PricingSourceFactory": ".pricing",
    "StaticPricingSource": ".pricing",
    # ledger
    "InMemorySpendLedger": ".ledger.in_memory",
    "LedgerDocument": ".ledger.base",
    "SpendLedger": ".ledger.base",
    "SpendLedgerFactory": ".ledger.factory",
    # gateway
    "LLMGateway": ".gateway.base",
    "LLMGatewayFactory": ".gateway.factory",
    # errors
    "CostError": ".errors",
    "LedgerBehindError": ".errors",
    "LedgerConflictError": ".errors",
    "LedgerError": ".errors",
    "UnsupportedCapabilityError": ".errors",
    "UsageRetrievalError": ".errors",
    "UsageTruncatedError": ".errors",
}

__all__ = sorted(_LAZY_EXPORTS)

if TYPE_CHECKING:  # pragma: no cover: static resolution only, preserves laziness at runtime
    from .attribution import AttributionContext, Attributor, AttributorFactory, DefaultAttributor
    from .errors import (
        CostError,
        LedgerBehindError,
        LedgerConflictError,
        LedgerError,
        UnsupportedCapabilityError,
        UsageRetrievalError,
        UsageTruncatedError,
    )
    from .gateway.base import LLMGateway
    from .gateway.factory import LLMGatewayFactory
    from .ledger.base import LedgerDocument, SpendLedger
    from .ledger.factory import SpendLedgerFactory
    from .ledger.in_memory import InMemorySpendLedger
    from .model import (
        ANONYMOUS_USER_ID,
        SYSTEM_USER_ID,
        AgentUsage,
        Attribution,
        BudgetDecision,
        BudgetLimit,
        BudgetPeriod,
        GatewayCapabilities,
        GatewayFilter,
        ModelSpend,
        ModelUsage,
        SessionUsage,
        SpendCursor,
        SpendTotal,
        UsageQuery,
        UsageReport,
        UsageResult,
        UsageWindow,
    )
    from .pricing import PassthroughPricingSource, PricingSource, PricingSourceFactory, StaticPricingSource


def __getattr__(name: str) -> Any:
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_path, __name__)
    return getattr(module, name)


def __dir__() -> list[str]:
    return sorted(__all__)
