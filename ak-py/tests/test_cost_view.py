"""UsageView (spec §13): the UsageViewContract, authorisation through the attributor, filter push-down, splitting the
window only on truncation, aggregation, and UsageViewFactory."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

import agentkernel.cost as cost
from agentkernel.core.config import _CostAttributionConfig, _CostPricingConfig, _CostViewConfig
from agentkernel.core.model import Principal
from agentkernel.core.util.factory import AKConfigError
from agentkernel.cost import (
    DefaultAttributor,
    DefaultUsageView,
    GatewayCapabilities,
    GatewayFilter,
    PassthroughPricingSource,
    StaticPricingSource,
    UnsupportedCapabilityError,
    UsageQuery,
    UsageResult,
    UsageRetrievalError,
    UsageTruncatedError,
    UsageView,
    UsageViewFactory,
)
from agentkernel.cost.testing import UsageViewContract, _row

_ALICE = Principal(subject="alice", provider="oidc")
_DAY = datetime(2026, 1, 5, tzinfo=timezone.utc)
_FIELDS = ("user_id", "agent_id", "session_id", "model", "provider")


class _RowsGateway:
    """fetch_usage over in-memory rows: filters only on what it declares, truncates above ``cap`` rows."""

    name = "fake"

    def __init__(self, rows, filters=frozenset(GatewayFilter), row_cap: int | None = 10_000, cap: int | None = None) -> None:
        self.capabilities = GatewayCapabilities(usage_retrieval=True, filters=frozenset(filters), row_cap=row_cap)
        self.rows = rows
        self.cap = cap
        self.queries: list[UsageQuery] = []

    async def fetch_usage(self, query: UsageQuery) -> UsageResult:
        unsupported = query.filters() - self.capabilities.filters
        assert not unsupported, f"the view pushed down {unsupported}"
        self.queries.append(query)
        matched = [
            row
            for row in self.rows
            if query.start <= row.timestamp < query.end
            and all(getattr(query, field) is None or getattr(row, field) == getattr(query, field) for field in _FIELDS)
        ]
        if self.cap is not None and len(matched) > self.cap:
            raise UsageTruncatedError("over the cap")
        return UsageResult(rows=matched)


def _view(gateway, pricing=None, attributor=None) -> DefaultUsageView:
    return DefaultUsageView(
        gateway,
        pricing or PassthroughPricingSource(_CostPricingConfig()),
        attributor or DefaultAttributor(_CostAttributionConfig()),
        _CostViewConfig(),
    )


def _query(**overrides) -> UsageQuery:
    return UsageQuery(**({"user_id": "alice", "start": _DAY, "end": _DAY + timedelta(days=1)} | overrides))


def _alice(row_id, at, **overrides):
    return _row(row_id, at, user_id="alice").model_copy(update=overrides)


class TestDefaultUsageViewContract(UsageViewContract):
    own_user_id = "alice"

    @pytest.fixture
    def view(self) -> UsageView:
        return _view(_RowsGateway([]))

    @pytest.fixture
    def principal(self) -> Principal:
        return _ALICE


class TestAuthorisation:
    @pytest.mark.asyncio
    async def test_a_prefixing_attributor_keys_the_query(self):
        from test_cost_attribution import PrefixingAttributor

        attributor = PrefixingAttributor(_CostAttributionConfig(type="x.Y", separator="|"))
        view = _view(_RowsGateway([]), attributor=attributor)

        with pytest.raises(PermissionError):
            await view.report(_query(user_id="alice"), _ALICE)  # the raw subject is not the attributed id
        assert (await view.report(_query(user_id="oidc|alice"), _ALICE)).user_id == "oidc|alice"


class TestPushDown:
    @pytest.mark.asyncio
    async def test_filters_the_gateway_lacks_apply_here(self):
        rows = [
            _alice("a", _DAY, agent_id="support", session_id="s1"),
            _alice("b", _DAY, agent_id="support", session_id="s2"),
            _alice("c", _DAY, agent_id="billing", session_id="s1"),
        ]
        gateway = _RowsGateway(rows, filters={GatewayFilter.USER, GatewayFilter.TIME_RANGE})

        report = await _view(gateway).report(_query(agent_id="support", session_id="s1"), _ALICE)

        assert report.total_input_tokens == 10 and [a.agent_id for a in report.agents] == ["support"]
        (sent,) = gateway.queries
        assert (sent.user_id, sent.agent_id, sent.session_id) == ("alice", None, None)

    @pytest.mark.asyncio
    async def test_a_gateway_that_cannot_filter_by_user_is_refused(self):
        gateway = _RowsGateway([], filters={GatewayFilter.TIME_RANGE})

        with pytest.raises(UnsupportedCapabilityError):
            await _view(gateway).report(_query(), _ALICE)


class TestSplitting:
    @staticmethod
    def _over(days: int, per_day: int, hours_apart: int = 1):
        return [_alice(f"d{d}-{n}", _DAY + timedelta(days=d, hours=n * hours_apart)) for d in range(days) for n in range(per_day)]

    @pytest.mark.asyncio
    async def test_under_the_cap_is_one_fetch(self):
        gateway = _RowsGateway(self._over(3, 2), cap=10)

        await _view(gateway).report(_query(end=_DAY + timedelta(days=3)), _ALICE)

        assert len(gateway.queries) == 1

    @pytest.mark.asyncio
    async def test_a_truncated_window_is_fetched_day_by_day(self):
        gateway = _RowsGateway(self._over(3, 2), cap=3)

        report = await _view(gateway).report(_query(end=_DAY + timedelta(days=3)), _ALICE)

        assert report.agents[0].requests == 6
        assert [(q.start, q.end) for q in gateway.queries[1:]] == [(_DAY + timedelta(days=d), _DAY + timedelta(days=d + 1)) for d in range(3)]

    @pytest.mark.asyncio
    async def test_a_truncated_day_is_fetched_hour_by_hour(self):
        gateway = _RowsGateway(self._over(1, 5), cap=3)

        report = await _view(gateway).report(_query(), _ALICE)

        assert report.agents[0].requests == 5
        assert len(gateway.queries) == 1 + 1 + 24  # the window, the day, its 24 hours

    @pytest.mark.asyncio
    async def test_a_truncated_hour_re_raises(self):
        gateway = _RowsGateway(self._over(1, 4, hours_apart=0), cap=3)

        with pytest.raises(UsageTruncatedError):
            await _view(gateway).report(_query(), _ALICE)

    @pytest.mark.asyncio
    async def test_without_a_row_cap_nothing_is_split(self):
        gateway = _RowsGateway(self._over(3, 2), row_cap=None, cap=3)

        with pytest.raises(UsageTruncatedError):
            await _view(gateway).report(_query(end=_DAY + timedelta(days=3)), _ALICE)
        assert len(gateway.queries) == 1


class TestAggregation:
    @pytest.mark.asyncio
    async def test_totals_billing_and_unpriced(self):
        rows = [
            _alice("a", _DAY, agent_id="support", cached_input_tokens=4, provider_cost=Decimal("0.5")),
            _alice("b", _DAY, agent_id="support", provider_cost=None),
            _alice("c", _DAY, agent_id=None, provider_cost=Decimal("1")),
            _row("bob", _DAY, user_id="bob"),
        ]
        pricing = StaticPricingSource(_CostPricingConfig(type="static", static={"markup": "2"}))

        report = await _view(_RowsGateway(rows, filters={GatewayFilter.TIME_RANGE, GatewayFilter.USER}), pricing).report(_query(), _ALICE)

        assert (report.total_cost, report.total_provider_cost, report.unpriced_requests) == (Decimal("3"), Decimal("1.5"), 1)
        assert (report.total_input_tokens, report.total_cached_input_tokens, report.currency) == (30, 4, "USD")
        assert [(a.agent_id, a.requests, a.cost) for a in report.agents] == [(None, 1, Decimal("2")), ("support", 2, Decimal("1"))]
        assert report.sessions is None

    @pytest.mark.asyncio
    async def test_sessions_only_when_the_query_names_an_agent_or_session(self):
        rows = [_alice("a", _DAY, agent_id="support", session_id="s1"), _alice("b", _DAY, agent_id="support", session_id="s2")]

        report = await _view(_RowsGateway(rows)).report(_query(agent_id="support"), _ALICE)

        assert [(s.agent_id, s.session_id, s.requests) for s in report.sessions] == [("support", "s1", 1), ("support", "s2", 1)]

    @pytest.mark.asyncio
    async def test_another_currency_is_a_retrieval_error(self):
        euro = _alice("a", _DAY).model_copy(update={"currency": "EUR"})

        with pytest.raises(UsageRetrievalError, match="EUR"):
            await _view(_RowsGateway([euro])).report(_query(), _ALICE)


class _CustomView(UsageView):
    async def report(self, query, principal):
        raise NotImplementedError


class TestUsageViewFactory:
    _ARGS = (_RowsGateway([]), PassthroughPricingSource(_CostPricingConfig()), DefaultAttributor(_CostAttributionConfig()))

    def test_default(self):
        assert type(UsageViewFactory.create(_CostViewConfig(), *self._ARGS)) is DefaultUsageView

    def test_a_dotted_path_gets_the_same_arguments(self):
        config = _CostViewConfig(type=f"{__name__}._CustomView", limit=5)

        view = UsageViewFactory.create(config, *self._ARGS)

        assert isinstance(view, _CustomView) and view.gateway is self._ARGS[0] and view.config is config

    def test_an_unknown_type_is_refused(self):
        with pytest.raises(AKConfigError, match="unknown cost.view.type"):
            UsageViewFactory.create(_CostViewConfig(type="fancy"), *self._ARGS)

    def test_exported(self):
        assert {"DefaultUsageView", "UsageView", "UsageViewFactory", "CostManager"} <= set(cost.__all__)
