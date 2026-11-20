"""Public testing helpers for cost management backends. Imports pytest, so import it from test code only."""

import copy
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from ..core.model import Principal
from .attribution import AttributionContext, Attributor
from .errors import UnsupportedCapabilityError, UsageRetrievalError
from .gateway.base import LLMGateway
from .model import Attribution, GatewayFilter, ModelUsage, SpendCursor, SpendTotal, UsageQuery, UsageWindow

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
