import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

import agentkernel.cost as cost
from agentkernel.core.config import _CostBudgetLimit
from agentkernel.core.model import Principal
from agentkernel.cost.errors import (
    CostError,
    LedgerBehindError,
    LedgerError,
    UnsupportedCapabilityError,
    UsageRetrievalError,
)
from agentkernel.cost.model import (
    ANONYMOUS_USER_ID,
    SYSTEM_USER_ID,
    AgentUsage,
    BudgetLimit,
    BudgetPeriod,
    GatewayFilter,
    ModelUsage,
    SpendCursor,
    SpendTotal,
    UsageQuery,
    UsageReport,
    UsageWindow,
)

UTC = timezone.utc


def _at(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def _row(row_id: str = "r1", **overrides) -> ModelUsage:
    fields = dict(
        user_id="alice",
        agent_id="a",
        session_id="s",
        request_id="q",
        provider="openai",
        model="gpt-4o-mini",
        input_tokens=10,
        output_tokens=5,
        cached_input_tokens=2,
        provider_cost=Decimal("0.01"),
        billed_cost=None,
        currency="USD",
        timestamp=_at(2026, 11, 19, 12),
        row_id=row_id,
    )
    fields.update(overrides)
    return ModelUsage(**fields)


# BudgetPeriod


@pytest.mark.parametrize(
    "period, now, start, end",
    [
        (BudgetPeriod.DAILY, _at(2026, 11, 19, 23, 59, 59), _at(2026, 11, 19), _at(2026, 11, 20)),
        (BudgetPeriod.DAILY, _at(2026, 12, 31, 12), _at(2026, 12, 31), _at(2027, 1, 1)),
        # 2026-11-22 is a Sunday; its week started Monday 2026-11-16
        (BudgetPeriod.WEEKLY, _at(2026, 11, 22, 23, 59, 59), _at(2026, 11, 16), _at(2026, 11, 23)),
        (BudgetPeriod.WEEKLY, _at(2026, 11, 23), _at(2026, 11, 23), _at(2026, 11, 30)),
        (BudgetPeriod.MONTHLY, _at(2026, 12, 31, 23, 59, 59), _at(2026, 12, 1), _at(2027, 1, 1)),
        (BudgetPeriod.MONTHLY, _at(2028, 2, 15), _at(2028, 2, 1), _at(2028, 3, 1)),
    ],
)
def test_budget_period_bounds(period, now, start, end):
    assert period.start_of(now) == start
    assert period.end_of(now) == end


def test_budget_period_converts_to_utc_first():
    # 03:00 on the 1st at +05:30 is still the previous day (and month) in UTC
    now = datetime(2026, 12, 1, 3, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert BudgetPeriod.DAILY.start_of(now) == _at(2026, 11, 30)
    assert BudgetPeriod.MONTHLY.start_of(now) == _at(2026, 11, 1)
    assert BudgetPeriod.MONTHLY.start_of(now).tzinfo == UTC


def test_budget_period_refuses_naive_datetime():
    with pytest.raises(ValueError, match="timezone-aware"):
        BudgetPeriod.DAILY.start_of(datetime(2026, 11, 19))


# SpendTotal


def test_spend_total_from_rows_groups_by_model():
    rows = [
        _row("r1"),
        _row("r2", provider_cost=Decimal("0.02"), input_tokens=None),
        _row("r3", provider="anthropic", model="claude", provider_cost=None),
        _row("r4", provider=None, model=None, output_tokens=None),
    ]
    total = SpendTotal.from_rows(rows, "usd")

    assert total.currency == "USD"
    assert set(total.by_model) == {"openai/gpt-4o-mini", "anthropic/claude", "/"}
    openai = total.by_model["openai/gpt-4o-mini"]
    assert (openai.requests, openai.input_tokens, openai.output_tokens, openai.cached_input_tokens) == (2, 10, 10, 4)
    assert (openai.provider_cost, openai.unpriced_requests) == (Decimal("0.03"), 0)
    anthropic = total.by_model["anthropic/claude"]
    assert (anthropic.requests, anthropic.provider_cost, anthropic.unpriced_requests) == (1, Decimal(0), 1)
    assert total.by_model["/"].output_tokens == 0


def test_spend_total_from_rows_refuses_other_currency():
    with pytest.raises(UsageRetrievalError, match="EUR"):
        SpendTotal.from_rows([_row(currency="eur")], "USD")


def test_spend_total_merge():
    ledger = SpendTotal.from_rows([_row("r1"), _row("r2", provider="anthropic", model="claude")], "USD")
    unsettled = SpendTotal.from_rows([_row("r3"), _row("r4", model="gpt-5", provider_cost=None)], "USD")

    merged = ledger.merge(unsettled)

    assert set(merged.by_model) == {"openai/gpt-4o-mini", "anthropic/claude", "openai/gpt-5"}
    assert merged.by_model["openai/gpt-4o-mini"].requests == 2
    assert merged.by_model["openai/gpt-4o-mini"].provider_cost == Decimal("0.02")
    assert merged.by_model["openai/gpt-5"].unpriced_requests == 1
    # inputs are left unchanged
    assert ledger.by_model["openai/gpt-4o-mini"].requests == 1
    assert "openai/gpt-5" not in ledger.by_model


def test_spend_total_merge_refuses_other_currency():
    with pytest.raises(UsageRetrievalError):
        SpendTotal(currency="USD", by_model={}).merge(SpendTotal(currency="EUR", by_model={}))


# Decimals and serialisation


def test_float_money_parses_through_str():
    assert _row(provider_cost=3.6e-06).provider_cost == Decimal("0.0000036")


def test_usage_report_json_writes_decimals_as_strings_and_keeps_extras():
    usage = dict(requests=1, cost=Decimal("0.1"), provider_cost=Decimal("0.0000036"), input_tokens=1, output_tokens=1)
    report = UsageReport(
        user_id="alice",
        currency="USD",
        window=UsageWindow(start=_at(2026, 11, 1), end=_at(2026, 12, 1)),
        total_cost=Decimal("0.1"),
        total_provider_cost=Decimal("0.0000036"),
        total_input_tokens=1,
        total_output_tokens=1,
        total_cached_input_tokens=0,
        unpriced_requests=0,
        agents=[AgentUsage(agent_id="a", cached_input_tokens=0, unpriced_requests=0, **usage)],
        tenant="acme",
    )
    data = json.loads(report.model_dump_json())
    assert data["total_cost"] == "0.1"
    assert Decimal(data["total_provider_cost"]) == Decimal("0.0000036")
    assert data["agents"][0]["cost"] == "0.1"
    assert data["tenant"] == "acme"
    assert UsageReport.ENVELOPE_KEYS == set(UsageReport.model_fields)
    assert "tenant" not in UsageReport.ENVELOPE_KEYS


# ModelUsage and UsageQuery


def test_model_usage_normalises_currency_and_timestamp():
    row = _row(currency="usd", timestamp=datetime(2026, 11, 19, 14, tzinfo=timezone(timedelta(hours=2))))
    assert row.currency == "USD"
    assert row.timestamp == _at(2026, 11, 19, 12)
    assert row.timestamp.tzinfo == UTC


def test_model_usage_refuses_naive_timestamp():
    with pytest.raises(ValidationError):
        _row(timestamp=datetime(2026, 11, 19))


def test_usage_query_filters():
    window = dict(start=_at(2026, 11, 1), end=_at(2026, 12, 1))
    assert UsageQuery(**window).filters() == {GatewayFilter.TIME_RANGE}
    assert UsageQuery(user_id="alice", model="gpt", **window).filters() == {
        GatewayFilter.USER,
        GatewayFilter.MODEL,
        GatewayFilter.TIME_RANGE,
    }


@pytest.mark.parametrize("end", [_at(2026, 11, 1), _at(2026, 10, 1)])
def test_usage_query_refuses_empty_window(end):
    with pytest.raises(ValidationError, match="start must be before end"):
        UsageQuery(start=_at(2026, 11, 1), end=end)


# Aliases, errors and the package surface


def test_aliases():
    assert BudgetLimit is _CostBudgetLimit
    assert SYSTEM_USER_ID == "ak-system"
    assert ANONYMOUS_USER_ID == Principal.anonymous().subject


def test_errors():
    assert issubclass(LedgerBehindError, LedgerError) and issubclass(LedgerError, CostError)
    unsupported = UnsupportedCapabilityError("litellm", "session_filter")
    assert "litellm" in str(unsupported) and "session_filter" in str(unsupported)
    assert UsageRetrievalError("down").auth is False
    behind = LedgerBehindError("alice", SpendCursor(timestamp=_at(2026, 11, 19), ids_at_timestamp=frozenset()))
    assert behind.user_id == "alice"


def test_package_exports_are_lazy(tmp_path):
    code = (
        "import sys, agentkernel.cost as c\n"
        "assert 'agentkernel.cost.model' not in sys.modules\n"
        "assert 'agentkernel.cost.errors' not in sys.modules\n"
        "assert c.SpendTotal.__module__ == 'agentkernel.cost.model'\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=tmp_path)
    assert result.returncode == 0, result.stderr


def test_package_unknown_name():
    with pytest.raises(AttributeError):
        cost.Nope
    assert set(cost.__all__) <= set(dir(cost))
