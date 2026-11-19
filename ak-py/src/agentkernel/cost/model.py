"""Data models of the cost management capability.

Monetary fields are ``Decimal`` everywhere. Pydantic converts a float input through ``str`` (``3.6e-06`` becomes
``Decimal("0.0000036")``) and writes ``Decimal`` to JSON as a string, so no client loses precision to a float.
"""

from collections.abc import Iterable
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from ..core.config import _COST_SYSTEM_USER_ID, _CostBudgetLimit, _CostBudgetPeriod
from ..core.meter import BudgetDecision  # re-export: lives in core because RunMeter.check returns it
from ..core.model import ANONYMOUS_PROVIDER
from .errors import UsageRetrievalError

# Defined in core/config.py because config may not import cost/ (spec deviation 15).
BudgetPeriod = _CostBudgetPeriod
BudgetLimit = _CostBudgetLimit

SYSTEM_USER_ID = _COST_SYSTEM_USER_ID
"""Billed for Agent Kernel's own calls made with no principal; reserved, so it cannot carry a configured budget."""

ANONYMOUS_USER_ID = ANONYMOUS_PROVIDER
"""The subject of ``Principal.anonymous()``."""


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc)


class Attribution(BaseModel):
    """Who a model call is billed to, sent to the gateway as headers."""

    model_config = ConfigDict(frozen=True)

    user_id: str | None
    agent_id: str | None = None
    session_id: str | None = None
    request_id: str | None = None


class ModelUsage(BaseModel):
    """One model call as the gateway recorded it."""

    user_id: str | None
    agent_id: str | None
    session_id: str | None
    request_id: str | None
    provider: str | None
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    cached_input_tokens: int | None
    provider_cost: Decimal | None
    billed_cost: Decimal | None  # set by the UsageView through PricingSource.bill
    currency: str  # ISO 4217, upper case
    timestamp: datetime  # UTC, tz-aware
    row_id: str  # the gateway's own id; used for the cursor and dedup only

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("timestamp")
    @classmethod
    def _utc_timestamp(cls, value: datetime) -> datetime:
        return _utc(value)


class GatewayFilter(StrEnum):
    """A dimension a gateway can filter usage on server-side."""

    USER = "user"
    AGENT = "agent"
    SESSION = "session"
    TIME_RANGE = "time_range"
    MODEL = "model"
    PROVIDER = "provider"


class GatewayCapabilities(BaseModel):
    """What a gateway can do, declared at class level on each gateway."""

    model_config = ConfigDict(frozen=True)

    usage_retrieval: bool = False
    cost_retrieval: bool = False
    user_aggregation: bool = False
    windowed_spend: bool = False
    agent_aggregation: bool = False
    session_filter: bool = False
    custom_metadata: bool = False
    native_user_budget: bool = False
    request_level_budget_check: bool = False
    streaming_usage: bool = False
    currencies: frozenset[str] = frozenset({"USD"})
    filters: frozenset[GatewayFilter] = frozenset()
    row_cap: int | None = None  # max rows one query returns before truncation


class UsageQuery(BaseModel):
    """A usage read: a UTC time range plus optional dimension filters."""

    user_id: str | None = None
    agent_id: str | None = None
    session_id: str | None = None
    start: datetime
    end: datetime
    model: str | None = None
    provider: str | None = None

    @model_validator(mode="after")
    def _check_window(self) -> "UsageQuery":
        self.start, self.end = _utc(self.start), _utc(self.end)
        if self.start >= self.end:
            raise ValueError("UsageQuery start must be before end")
        return self

    def filters(self) -> frozenset[GatewayFilter]:
        """The dimensions this query filters on: the ones set, plus the time range."""
        dimensions = {
            GatewayFilter.USER: self.user_id,
            GatewayFilter.AGENT: self.agent_id,
            GatewayFilter.SESSION: self.session_id,
            GatewayFilter.MODEL: self.model,
            GatewayFilter.PROVIDER: self.provider,
        }
        return frozenset({GatewayFilter.TIME_RANGE, *(f for f, value in dimensions.items() if value is not None)})


class UsageResult(BaseModel):
    """Every row of a usage read, all pages, in gateway order."""

    rows: list[ModelUsage]


class ModelSpend(BaseModel):
    """Spend on one provider/model pair."""

    model: str | None
    provider: str | None
    requests: int = 0
    input_tokens: int = 0  # unknown counts add 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    provider_cost: Decimal = Decimal(0)
    unpriced_requests: int = 0

    def add(self, other: "ModelSpend") -> "ModelSpend":
        return ModelSpend(
            model=self.model,
            provider=self.provider,
            requests=self.requests + other.requests,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            provider_cost=self.provider_cost + other.provider_cost,
            unpriced_requests=self.unpriced_requests + other.unpriced_requests,
        )


class SpendTotal(BaseModel):
    """A user's spend in one currency, by model."""

    currency: str
    by_model: dict[str, ModelSpend]  # key: f"{provider}/{model}", "" for None

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, value: str) -> str:
        return value.upper()

    @staticmethod
    def key(provider: str | None, model: str | None) -> str:
        return f"{provider or ''}/{model or ''}"

    @classmethod
    def from_rows(cls, rows: Iterable[ModelUsage], currency: str) -> "SpendTotal":
        """Sum rows by model. Unknown token counts add 0; a row without a cost counts as unpriced."""
        total = cls(currency=currency, by_model={})
        for row in rows:
            if row.currency != total.currency:
                raise UsageRetrievalError(f"usage row {row.row_id!r} is in {row.currency}, expected {total.currency}")
            spend = ModelSpend(
                model=row.model,
                provider=row.provider,
                requests=1,
                input_tokens=row.input_tokens or 0,
                output_tokens=row.output_tokens or 0,
                cached_input_tokens=row.cached_input_tokens or 0,
                provider_cost=row.provider_cost if row.provider_cost is not None else Decimal(0),
                unpriced_requests=1 if row.provider_cost is None else 0,
            )
            key = cls.key(row.provider, row.model)
            total.by_model[key] = total.by_model[key].add(spend) if key in total.by_model else spend
        return total

    def merge(self, other: "SpendTotal") -> "SpendTotal":
        """A new total holding both; used to add unsettled rows to a ledger aggregate."""
        if other.currency != self.currency:
            raise UsageRetrievalError(f"cannot merge spend in {other.currency} into spend in {self.currency}")
        by_model = dict(self.by_model)
        for key, spend in other.by_model.items():
            by_model[key] = by_model[key].add(spend) if key in by_model else spend
        return SpendTotal(currency=self.currency, by_model=by_model)


class UsageWindow(BaseModel):
    start: datetime
    end: datetime


class AgentUsage(BaseModel):
    agent_id: str | None
    requests: int
    cost: Decimal
    provider_cost: Decimal
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    unpriced_requests: int


class SessionUsage(AgentUsage):
    session_id: str | None


class UsageReport(BaseModel):
    """A user's usage over a window. The envelope is fixed; a custom view may add keys."""

    model_config = ConfigDict(extra="allow")

    user_id: str
    currency: str
    window: UsageWindow
    total_cost: Decimal
    total_provider_cost: Decimal
    total_input_tokens: int
    total_output_tokens: int
    total_cached_input_tokens: int
    unpriced_requests: int
    agents: list[AgentUsage]
    sessions: list[SessionUsage] | None = None  # set only when the query names agent_id or session_id

    ENVELOPE_KEYS: ClassVar[frozenset[str]]


UsageReport.ENVELOPE_KEYS = frozenset(UsageReport.model_fields)


class SpendCursor(BaseModel):
    """How far a spend ledger has applied the gateway's rows."""

    timestamp: datetime  # last settled gateway timestamp applied
    ids_at_timestamp: frozenset[str]  # row ids already applied at exactly that timestamp
