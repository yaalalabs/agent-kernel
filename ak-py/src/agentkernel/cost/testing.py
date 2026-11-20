"""Public testing helpers for cost management backends. Imports pytest, so import it from test code only."""

import asyncio
import copy
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from ..core.meter import BudgetDecision
from ..core.model import Principal
from .attribution import AttributionContext, Attributor
from .budget import DEFAULT_DENY_MESSAGE, UNVERIFIED_DENY_MESSAGE, BudgetPolicy
from .errors import UnsupportedCapabilityError, UsageRetrievalError
from .gateway.base import LLMGateway
from .ledger.base import SpendLedger
from .model import (
    SYSTEM_USER_ID,
    Attribution,
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
from .pricing import PricingSource
from .view import UsageView

_USER = "contract-user"
_T0 = datetime(2026, 1, 5, 12, 0, 0, tzinfo=timezone.utc)
# Ids a gateway must carry safely: header injection, a list separator, non-ASCII.
_AWKWARD_IDS = ("line\r\nbreak", "comma,separated", "ünïcødé")
_FAIL_MODES = ("unreachable", "auth", "server", "malformed")


def _row(
    row_id: str,
    timestamp: datetime,
    *,
    user_id: str = _USER,
    model: str = "gpt-4o",
    cached_input_tokens: int | None = None,
    provider_cost: Decimal | None = Decimal("0.001"),
) -> ModelUsage:
    return ModelUsage(
        user_id=user_id,
        agent_id=None,
        session_id=None,
        request_id=None,
        provider="openai",
        model=model,
        input_tokens=10,
        output_tokens=5,
        cached_input_tokens=cached_input_tokens,
        provider_cost=provider_cost,
        billed_cost=None,
        currency="USD",
        timestamp=timestamp,
        row_id=row_id,
    )


def _window_query(user_id: str = _USER) -> UsageQuery:
    return UsageQuery(user_id=user_id, start=_T0 - timedelta(hours=1), end=_T0 + timedelta(hours=1))


class LLMGatewayContract:
    """Conformance suite every LLMGateway subclasses. Override `gateway`, `seed` and `fail`.

    Cases needing a capability the gateway does not declare are skipped. Not prefixed ``Test`` so pytest does not
    collect it on its own.
    """

    # Rows one server page holds; fetch_usage_since returns at most this many. At least 3, so two rows sharing a
    # timestamp fit in a page with a later one.
    page_size: int = 3

    @pytest.fixture
    def gateway(self) -> LLMGateway:
        """The gateway under contract, over a fake backend; every subclass must override this fixture."""
        raise NotImplementedError("subclasses must override the `gateway` fixture")

    def seed(self, gateway: LLMGateway, rows: list[ModelUsage]) -> None:
        """Store ``rows`` in the fake backend as the gateway would have recorded them: ids through
        ``gateway.gateway_user_id``. Every subclass must override this."""
        raise NotImplementedError("subclasses must override `seed`")

    def fail(self, gateway: LLMGateway, mode: str) -> None:
        """Make every later backend read fail: ``unreachable``, ``auth`` (401), ``server`` (5xx) or ``malformed``.

        A mode the backend cannot produce calls ``pytest.skip``. Every subclass must override this.
        """
        raise NotImplementedError("subclasses must override `fail`")

    @staticmethod
    def _require(gateway: LLMGateway, capability: str) -> None:
        if not getattr(gateway.capabilities, capability):
            pytest.skip(f"gateway does not declare {capability}")

    # Headers and the id transform (coupling rule 5)

    @pytest.mark.parametrize("awkward", _AWKWARD_IDS)
    def test_contract_headers_never_carry_cr_or_lf(self, gateway, awkward):
        headers = gateway.attribution_headers(Attribution(user_id=awkward, agent_id=awkward, session_id=awkward, request_id=awkward))

        assert all("\r" not in text and "\n" not in text for item in headers.items() for text in item)

    @pytest.mark.asyncio
    async def test_contract_awkward_user_ids_round_trip_through_rows(self, gateway):
        self._require(gateway, "usage_retrieval")
        self.seed(gateway, [_row(f"id-{n}", _T0 + timedelta(seconds=n), user_id=uid) for n, uid in enumerate(_AWKWARD_IDS)])

        for uid in _AWKWARD_IDS:
            result = await gateway.fetch_usage(_window_query(uid))

            assert [row.user_id for row in result.rows] == [uid]

    # Capabilities

    @pytest.mark.asyncio
    async def test_contract_operations_match_declared_capabilities(self, gateway):
        operations: dict[str, list[Callable[[], Awaitable[object]]]] = {
            "usage_retrieval": [
                lambda: gateway.fetch_usage(_window_query()),
                lambda: gateway.fetch_usage_since(_USER, None, _T0),
            ],
            "windowed_spend": [lambda: gateway.total_spend(_USER, UsageWindow(start=_T0 - timedelta(hours=1), end=_T0))],
            "native_user_budget": [lambda: gateway.sync_budget_definitions([]), lambda: gateway.sync_budgets({})],
        }
        for capability, calls in operations.items():
            for call in calls:
                if getattr(gateway.capabilities, capability):
                    await call()  # declared: must not raise UnsupportedCapabilityError
                else:
                    with pytest.raises(UnsupportedCapabilityError):
                        await call()

    @pytest.mark.asyncio
    async def test_contract_filter_outside_capabilities_raises(self, gateway):
        self._require(gateway, "usage_retrieval")
        values = {
            GatewayFilter.USER: "user_id",
            GatewayFilter.AGENT: "agent_id",
            GatewayFilter.SESSION: "session_id",
            GatewayFilter.MODEL: "model",
            GatewayFilter.PROVIDER: "provider",
        }
        missing = [f for f in values if f not in gateway.capabilities.filters]
        if not missing:
            pytest.skip("gateway filters on every dimension")
        query = _window_query().model_copy(update={values[missing[0]]: "x"})

        with pytest.raises(UnsupportedCapabilityError):
            await gateway.fetch_usage(query)

    def test_contract_bare_429_is_not_a_budget_refusal(self, gateway):
        class RateLimited(Exception):
            status_code = 429

        assert gateway.is_budget_refusal(RateLimited("Too Many Requests")) is False

    # Reads

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", _FAIL_MODES)
    async def test_contract_failed_read_raises_never_zero(self, gateway, mode):
        self._require(gateway, "usage_retrieval")
        self.seed(gateway, [_row("r0", _T0)])
        self.fail(gateway, mode)

        with pytest.raises(UsageRetrievalError):
            await gateway.fetch_usage(_window_query())
        with pytest.raises(UsageRetrievalError):
            await gateway.fetch_usage_since(_USER, None, _T0 + timedelta(hours=1))
        if gateway.capabilities.windowed_spend:
            with pytest.raises(UsageRetrievalError):
                await gateway.total_spend(_USER, UsageWindow(start=_T0 - timedelta(hours=1), end=_T0 + timedelta(hours=1)))

    @pytest.mark.asyncio
    async def test_contract_pages_are_concatenated_in_order(self, gateway):
        self._require(gateway, "usage_retrieval")
        rows = [_row(f"r{n:05d}", _T0 + timedelta(seconds=n)) for n in range(2 * self.page_size + 1)]
        self.seed(gateway, rows)

        result = await gateway.fetch_usage(_window_query())

        assert [row.row_id for row in result.rows] == [row.row_id for row in rows]

    @pytest.mark.asyncio
    async def test_contract_windowed_spend_equals_summed_rows(self, gateway):
        self._require(gateway, "usage_retrieval")
        self._require(gateway, "windowed_spend")
        self.seed(
            gateway,
            [
                _row("r0", _T0, cached_input_tokens=4),
                _row("r1", _T0 + timedelta(seconds=1), model="gpt-4o-mini", provider_cost=None),
                _row("r2", _T0 + timedelta(seconds=2), provider_cost=Decimal("0.0025")),
            ],
        )
        window = UsageWindow(start=_T0 - timedelta(hours=1), end=_T0 + timedelta(hours=1))

        total = await gateway.total_spend(_USER, window)
        rows = (await gateway.fetch_usage(_window_query())).rows

        assert total == SpendTotal.from_rows(rows, "USD")

    # fetch_usage_since

    @pytest.mark.asyncio
    async def test_contract_since_resumes_inside_a_shared_timestamp(self, gateway):
        self._require(gateway, "usage_retrieval")
        shared = _T0 + timedelta(microseconds=500_000)
        self.seed(gateway, [_row("a", shared), _row("b", shared), _row("c", _T0 + timedelta(seconds=1))])

        rows, cursor, caught_up = await gateway.fetch_usage_since(
            _USER, SpendCursor(timestamp=shared, ids_at_timestamp=frozenset({"a"})), _T0 + timedelta(seconds=1)
        )

        assert [row.row_id for row in rows] == ["b", "c"]
        assert caught_up is True
        assert cursor == SpendCursor(timestamp=_T0 + timedelta(seconds=1), ids_at_timestamp=frozenset({"c"}))

    @pytest.mark.asyncio
    async def test_contract_since_bounds_are_exact_within_a_second(self, gateway):
        self._require(gateway, "usage_retrieval")
        at = _T0 + timedelta(microseconds=500_000)  # the cursor; "at" itself is covered by the shared-timestamp case
        self.seed(
            gateway,
            [
                _row("before", _T0 + timedelta(microseconds=200_000)),  # earlier in the cursor's second
                _row("next", _T0 + timedelta(microseconds=700_000)),
                _row("past-until", _T0 + timedelta(microseconds=900_000)),  # same second, after until
            ],
        )

        rows, _, caught_up = await gateway.fetch_usage_since(
            _USER, SpendCursor(timestamp=at, ids_at_timestamp=frozenset({"at"})), _T0 + timedelta(microseconds=800_000)
        )

        assert [row.row_id for row in rows] == ["next"]
        assert caught_up is True

    @pytest.mark.asyncio
    async def test_contract_since_drains_in_batches_without_gaps_or_repeats(self, gateway):
        self._require(gateway, "usage_retrieval")
        # Pairs of rows share a timestamp, so batch edges can fall inside one.
        rows = [_row(f"r{n:05d}", _T0 + timedelta(seconds=n // 2)) for n in range(3 * self.page_size + 1)]
        self.seed(gateway, rows)
        until = rows[-1].timestamp

        seen: list[str] = []
        cursor: SpendCursor | None = None
        caught_up = False
        for _ in range(len(rows) + 1):
            batch, cursor, caught_up = await gateway.fetch_usage_since(_USER, cursor, until)
            assert len(batch) <= self.page_size
            seen += [row.row_id for row in batch]
            if caught_up:
                break
            assert batch, "a batch that is not caught up must make progress"

        assert caught_up is True
        assert seen == [row.row_id for row in rows]


_USER_PRINCIPAL = Principal(subject="user-123", provider="oidc", namespace="https://issuer.example")
_CONTEXT = AttributionContext(principal=_USER_PRINCIPAL, agent_name="support", session_id="s-1", request_id="r-1")


class AttributorContract:
    """Conformance suite every Attributor subclasses. Override `attributor`.

    Not prefixed ``Test`` so pytest does not collect it on its own.
    """

    @pytest.fixture
    def attributor(self) -> Attributor:
        """The attributor under contract; every subclass must override this fixture."""
        raise NotImplementedError("subclasses must override the `attributor` fixture")

    def test_contract_same_context_same_attribution(self, attributor):
        assert attributor.resolve(_CONTEXT) == attributor.resolve(_CONTEXT)

    def test_contract_session_data_never_changes_the_user(self, attributor):
        other = AttributionContext(principal=_USER_PRINCIPAL, agent_name="billing", session_id="s-2", request_id="r-2")

        assert attributor.resolve(other).user_id == attributor.resolve(_CONTEXT).user_id

    def test_contract_the_acting_agent_never_becomes_the_user(self, attributor):
        """The spoofing rule (§9): the run's principal carries the agent as ``actor``; the user comes from the subject."""
        acting = AttributionContext(
            principal=_USER_PRINCIPAL.with_actor(Principal(subject="support", kind="agent", provider="agent")),
            agent_name="support",
            session_id="s-1",
            request_id="r-1",
        )

        assert attributor.resolve(acting).user_id == attributor.resolve(_CONTEXT).user_id

    def test_contract_the_context_is_left_unchanged(self, attributor):
        before = copy.deepcopy(_CONTEXT)

        attributor.resolve(_CONTEXT)

        assert _CONTEXT == before and _CONTEXT.principal == before.principal

    def test_contract_session_and_request_are_the_runs(self, attributor):
        attribution = attributor.resolve(_CONTEXT)

        assert isinstance(attribution, Attribution)
        assert (attribution.session_id, attribution.request_id) == ("s-1", "r-1")


class PricingSourceContract:
    """Conformance suite every PricingSource subclasses. Override `source`, and set `rated_model` when the source
    prices some model from its token counts (the cases about rates skip without one).

    Not prefixed ``Test`` so pytest does not collect it on its own.
    """

    rated_model: str | None = None

    @pytest.fixture
    def source(self) -> PricingSource:
        """The pricing source under contract; every subclass must override this fixture."""
        raise NotImplementedError("subclasses must override the `source` fixture")

    def _usage(self, row_id: str, model: str, *, input_tokens, cached, output, cost) -> ModelUsage:
        return _row(row_id, _T0, model=model, cached_input_tokens=cached, provider_cost=cost).model_copy(
            update={"input_tokens": input_tokens, "output_tokens": output}
        )

    def test_contract_unknown_in_unknown_out(self, source):
        unknown = self._usage("r0", self.rated_model or "unrated-model", input_tokens=None, cached=None, output=None, cost=None)

        assert source.bill(unknown) is None

    def test_contract_a_cached_token_is_charged_once(self, source):
        if self.rated_model is None:
            pytest.skip("the source prices no model from token counts")
        model = self.rated_model

        def bill(input_tokens, cached):
            return source.bill(self._usage("r", model, input_tokens=input_tokens, cached=cached, output=0, cost=None))

        assert bill(1000, 400) == bill(600, 0) + bill(400, 400)

    def test_contract_bill_total_equals_the_sum_of_row_bills(self, source):
        rows = [
            self._usage("u1", "unrated-model", input_tokens=10, cached=None, output=5, cost=Decimal("0.0021")),
            self._usage("u2", "unrated-model", input_tokens=None, cached=None, output=None, cost=Decimal("0.5")),
            self._usage("u3", "unrated-model", input_tokens=7, cached=None, output=1, cost=None),  # unpriced
        ]
        if self.rated_model is not None:
            rows += [
                self._usage("r1", self.rated_model, input_tokens=1200, cached=300, output=450, cost=None),
                self._usage("r2", self.rated_model, input_tokens=80, cached=None, output=None, cost=Decimal("9")),
                self._usage("r3", self.rated_model, input_tokens=None, cached=None, output=None, cost=None),
            ]
        bills = [source.bill(row) for row in rows]

        assert source.bill_total(SpendTotal.from_rows(rows, "USD")) == sum((b for b in bills if b is not None), Decimal(0))

    def test_contract_bills_at_cost_is_declared(self, source):
        assert isinstance(source.bills_at_cost, bool)


class LedgerClock:
    """A settable UTC clock for spend-ledger tests: pass it as the ledger's ``clock`` and set ``now``."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


_LEDGER_NOW = datetime(2026, 1, 28, 12, 0, tzinfo=timezone.utc)  # a Wednesday


class SpendLedgerContract:
    """Conformance suite every SpendLedger subclasses. Override `ledger`, building it with every ``BudgetPeriod``,
    ``ttl=0`` and ``clock=clock``.

    A backend whose store expires keys by itself (Redis ``EX``, DynamoDB TTL) overrides
    ``test_contract_an_expired_document_is_gone`` with its own check. Not prefixed ``Test`` so pytest does not collect
    it on its own.
    """

    @pytest.fixture
    def clock(self) -> LedgerClock:
        return LedgerClock(_LEDGER_NOW)

    @pytest.fixture
    def ledger(self, clock) -> SpendLedger:
        """The ledger under contract; every subclass must override this fixture."""
        raise NotImplementedError("subclasses must override the `ledger` fixture")

    @staticmethod
    def _cursor(at: datetime, *ids: str) -> SpendCursor:
        return SpendCursor(timestamp=at, ids_at_timestamp=frozenset(ids))

    @pytest.mark.asyncio
    async def test_contract_a_missing_user_has_nothing(self, ledger):
        assert await ledger.load("nobody") is None
        assert await ledger.cursor("nobody") is None
        assert (await ledger.read("nobody", BudgetPeriod.MONTHLY, _LEDGER_NOW)).by_model == {}

    @pytest.mark.asyncio
    async def test_contract_added_rows_read_back_per_period(self, ledger):
        rows = [_row("r1", _LEDGER_NOW, cached_input_tokens=3), _row("r2", _LEDGER_NOW, model="gpt-4o-mini", provider_cost=None)]

        assert await ledger.add(_USER, rows, None, self._cursor(_LEDGER_NOW, "r1", "r2")) is True

        expected = SpendTotal.from_rows(rows, "USD")
        for period in BudgetPeriod:
            assert await ledger.read(_USER, period, _LEDGER_NOW) == expected
        assert await ledger.cursor(_USER) == self._cursor(_LEDGER_NOW, "r1", "r2")

    @pytest.mark.asyncio
    async def test_contract_rows_bucket_at_utc_period_edges(self, ledger):
        # The clock stays at Wednesday 28 Jan, so Tuesday's day bucket is still retained (current and previous day).
        day_end = datetime(2026, 1, 27, 23, 59, 59, 999999, tzinfo=timezone.utc)
        rows = [
            _row("day-end", day_end),
            _row("day-start", day_end + timedelta(microseconds=1)),  # Wednesday 00:00
            _row("month-end", datetime(2026, 1, 31, 12, tzinfo=timezone.utc)),  # Saturday
            _row("sunday", datetime(2026, 2, 1, 12, tzinfo=timezone.utc)),  # 1st of the month
            _row("monday", datetime(2026, 2, 2, 0, tzinfo=timezone.utc)),
        ]
        await ledger.add(_USER, rows, None, self._cursor(rows[-1].timestamp, "monday"))

        async def requests(period: BudgetPeriod, at: datetime) -> int:
            return sum(spend.requests for spend in (await ledger.read(_USER, period, at)).by_model.values())

        assert await requests(BudgetPeriod.DAILY, day_end) == 1
        assert await requests(BudgetPeriod.DAILY, day_end + timedelta(microseconds=1)) == 1
        assert await requests(BudgetPeriod.WEEKLY, datetime(2026, 2, 1, tzinfo=timezone.utc)) == 4  # Mon 26 Jan - Sun 1 Feb
        assert await requests(BudgetPeriod.WEEKLY, datetime(2026, 2, 2, tzinfo=timezone.utc)) == 1
        assert await requests(BudgetPeriod.MONTHLY, datetime(2026, 1, 15, tzinfo=timezone.utc)) == 3
        assert await requests(BudgetPeriod.MONTHLY, datetime(2026, 2, 15, tzinfo=timezone.utc)) == 2

    @pytest.mark.asyncio
    async def test_contract_a_stale_cursor_adds_nothing(self, ledger):
        first = self._cursor(_LEDGER_NOW, "r1")
        await ledger.add(_USER, [_row("r1", _LEDGER_NOW)], None, first)

        assert await ledger.add(_USER, [_row("r2", _LEDGER_NOW)], None, self._cursor(_LEDGER_NOW, "r2")) is False

        assert await ledger.cursor(_USER) == first
        assert (await ledger.read(_USER, BudgetPeriod.DAILY, _LEDGER_NOW)).by_model["openai/gpt-4o"].requests == 1

    @pytest.mark.asyncio
    async def test_contract_two_concurrent_adds_from_one_cursor_count_once(self, ledger):
        rows = [_row("r1", _LEDGER_NOW), _row("r2", _LEDGER_NOW)]
        cursor = self._cursor(_LEDGER_NOW, "r1", "r2")

        results = await asyncio.gather(ledger.add(_USER, rows, None, cursor), ledger.add(_USER, rows, None, cursor))

        assert sorted(results) == [False, True]
        assert (await ledger.read(_USER, BudgetPeriod.DAILY, _LEDGER_NOW)).by_model["openai/gpt-4o"].requests == 2

    @pytest.mark.asyncio
    async def test_contract_compare_and_set_refuses_a_stale_version(self, ledger):
        await ledger.add(_USER, [_row("r1", _LEDGER_NOW)], None, self._cursor(_LEDGER_NOW, "r1"))
        stored = await ledger.load(_USER)
        assert stored is not None
        changed = stored.model_copy(update={"cursor": None, "version": stored.version + 1})

        assert await ledger.compare_and_set(_USER, stored.version - 1, changed, _LEDGER_NOW + timedelta(days=1)) is False
        assert await ledger.load(_USER) == stored

    @pytest.mark.asyncio
    async def test_contract_buckets_older_than_the_previous_period_are_pruned(self, ledger, clock):
        await ledger.add(_USER, [_row("jan", _LEDGER_NOW)], None, self._cursor(_LEDGER_NOW, "jan"))
        clock.now = later = datetime(2026, 2, 5, 12, tzinfo=timezone.utc)  # the document lives until 1 March

        assert await ledger.add(_USER, [_row("feb", later)], self._cursor(_LEDGER_NOW, "jan"), self._cursor(later, "feb"))

        doc = await ledger.load(_USER)
        assert doc is not None
        jan_28 = f"|{_LEDGER_NOW.replace(hour=0).isoformat()}|"
        assert not [key for key in doc.buckets if key.startswith("daily") and jan_28 in key]  # two days ago: gone
        assert [key for key in doc.buckets if key.startswith("weekly") and "2026-01-26" in key]  # the previous week: kept
        assert [key for key in doc.buckets if key.startswith("monthly") and "2026-01-01" in key]  # the previous month: kept

    @pytest.mark.asyncio
    async def test_contract_expiry_outlives_every_period_by_one(self, ledger, monkeypatch):
        seen: list[datetime] = []
        original = ledger.compare_and_set

        async def recording(user_id, expected_version, doc, expires_at):
            seen.append(expires_at)
            return await original(user_id, expected_version, doc, expires_at)

        monkeypatch.setattr(ledger, "compare_and_set", recording)
        await ledger.add(_USER, [_row("r1", _LEDGER_NOW)], None, self._cursor(_LEDGER_NOW, "r1"))

        assert seen == [max(period.end_of(period.end_of(_LEDGER_NOW)) for period in BudgetPeriod)]

    @pytest.mark.asyncio
    async def test_contract_an_expired_document_is_gone(self, ledger, clock):
        await ledger.add(_USER, [_row("r1", _LEDGER_NOW)], None, self._cursor(_LEDGER_NOW, "r1"))
        clock.now = max(period.end_of(period.end_of(_LEDGER_NOW)) for period in BudgetPeriod)

        assert await ledger.load(_USER) is None

    @pytest.mark.asyncio
    async def test_contract_an_expired_document_is_replaced_from_scratch(self, ledger, clock):
        """A store that deletes expired documents late must still let a fresh document replace one."""
        await ledger.add(_USER, [_row("old", _LEDGER_NOW)], None, self._cursor(_LEDGER_NOW, "old"))
        clock.now = later = max(period.end_of(period.end_of(_LEDGER_NOW)) for period in BudgetPeriod)

        assert await ledger.add(_USER, [_row("new", later)], None, self._cursor(later, "new")) is True

        assert await ledger.cursor(_USER) == self._cursor(later, "new")
        assert (await ledger.read(_USER, BudgetPeriod.MONTHLY, later)).by_model["openai/gpt-4o"].requests == 1

    @pytest.mark.asyncio
    async def test_contract_a_row_in_another_currency_adds_nothing(self, ledger):
        euro = _row("r1", _LEDGER_NOW).model_copy(update={"currency": "EUR"})

        with pytest.raises(UsageRetrievalError):
            await ledger.add(_USER, [euro], None, self._cursor(_LEDGER_NOW, "r1"))
        assert await ledger.load(_USER) is None


class BudgetPolicyContract:
    """Conformance suite every BudgetPolicy subclasses. Override `make_policy`, `spend` and `reads`.

    Not prefixed ``Test`` so pytest does not collect it on its own.
    """

    def make_policy(self, limit: BudgetLimit, on_error: str) -> BudgetPolicy:
        """A policy whose budget for every user is ``limit``; every subclass must override this."""
        raise NotImplementedError("subclasses must override `make_policy`")

    def spend(self, policy: BudgetPolicy, result: Decimal | Exception) -> None:
        """Make the policy's next spend read bill ``result``, or raise it; every subclass must override this."""
        raise NotImplementedError("subclasses must override `spend`")

    def reads(self, policy: BudgetPolicy) -> int:
        """How many spend reads the policy made; every subclass must override this."""
        raise NotImplementedError("subclasses must override `reads`")

    @staticmethod
    def _limit(**overrides) -> BudgetLimit:
        return BudgetLimit(**({"amount": Decimal("10")} | overrides))

    @pytest.mark.asyncio
    async def test_contract_under_the_budget_is_allowed(self):
        policy = self.make_policy(self._limit(), "block")
        self.spend(policy, Decimal("9.99"))

        assert await policy.check(Attribution(user_id="alice")) == BudgetDecision.allow()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("spent", [Decimal("10"), Decimal("12.5")])
    async def test_contract_at_or_over_the_budget_is_denied(self, spent):
        policy = self.make_policy(self._limit(), "block")
        self.spend(policy, spent)
        custom = self.make_policy(self._limit(message="Monthly limit reached."), "block")
        self.spend(custom, spent)

        assert await policy.check(Attribution(user_id="alice")) == BudgetDecision.deny(DEFAULT_DENY_MESSAGE)
        assert await custom.check(Attribution(user_id="alice")) == BudgetDecision.deny("Monthly limit reached.")

    @pytest.mark.asyncio
    async def test_contract_a_warn_budget_warns_naming_the_user(self):
        policy = self.make_policy(self._limit(action="warn"), "block")
        self.spend(policy, Decimal("11"))

        decision = await policy.check(Attribution(user_id="alice"))

        assert decision.kind == "warn" and "alice" in (decision.message or "")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("user_id", [None, SYSTEM_USER_ID])
    async def test_contract_unattributed_and_system_calls_are_allowed_unread(self, user_id):
        policy = self.make_policy(self._limit(), "block")
        self.spend(policy, Decimal("1000"))

        assert await policy.check(Attribution(user_id=user_id)) == BudgetDecision.allow()
        assert self.reads(policy) == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("on_error", "expected"), [("block", BudgetDecision.deny(UNVERIFIED_DENY_MESSAGE)), ("allow", BudgetDecision.allow())])
    async def test_contract_a_failed_read_follows_on_error(self, on_error, expected):
        policy = self.make_policy(self._limit(), on_error)
        self.spend(policy, UsageRetrievalError("gateway down", gateway="fake"))

        assert await policy.check(Attribution(user_id="alice")) == expected


class UsageViewContract:
    """Conformance suite every UsageView subclasses. Override `view` and `principal`; the principal's attributed id is
    the user the view has usage for.

    Not prefixed ``Test`` so pytest does not collect it on its own.
    """

    @pytest.fixture
    def view(self) -> UsageView:
        """The view under contract; every subclass must override this fixture."""
        raise NotImplementedError("subclasses must override the `view` fixture")

    @pytest.fixture
    def principal(self) -> Principal:
        """A principal whose attributed id is ``own_user_id``; every subclass must override this fixture."""
        raise NotImplementedError("subclasses must override the `principal` fixture")

    own_user_id: str = _USER

    def _query(self, user_id: str) -> UsageQuery:
        return UsageQuery(user_id=user_id, start=_T0 - timedelta(days=1), end=_T0 + timedelta(days=1))

    @pytest.mark.asyncio
    async def test_contract_the_report_keeps_the_envelope(self, view, principal):
        report = await view.report(self._query(self.own_user_id), principal)

        assert UsageReport.ENVELOPE_KEYS <= set(report.model_dump())
        assert report.user_id == self.own_user_id

    @pytest.mark.asyncio
    async def test_contract_another_users_usage_is_refused(self, view, principal):
        with pytest.raises(PermissionError):
            await view.report(self._query(f"{self.own_user_id}-other"), principal)
