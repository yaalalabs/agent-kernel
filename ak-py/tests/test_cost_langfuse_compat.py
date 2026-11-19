"""Langfuse compatibility suite (spec §5.3): the header and route contract LangfuseGateway depends on.

The Langfuse AI Gateway is beta, so the shapes are pinned here against the vendor itself. The fake v2 observations
route validates every response with the SDK's generated model (``langfuse.api`` 4.15), and the query parameter
names are checked against the SDK's own request code. Ordering (newest first), millisecond time filters, and empty
pages that still carry a cursor follow the server (``packages/shared/src/server/repositories/events.ts``).
"""

import base64
import inspect
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import httpx
import pytest
from langfuse.api.core.pydantic_utilities import parse_obj_as
from langfuse.api.observations.raw_client import AsyncRawObservationsClient
from langfuse.api.observations.types import ObservationsV2Response

from agentkernel.core.config import _CostGatewayConfig
from agentkernel.core.util.factory import AKConfigError
from agentkernel.cost import Attribution, LLMGatewayFactory, ModelUsage, SpendCursor, UsageQuery, UsageWindow
from agentkernel.cost.gateway.langfuse import LangfuseGateway
from agentkernel.cost.testing import LLMGatewayContract
from agentkernel.secret import SecretManager

_T0 = datetime(2026, 1, 5, 12, 0, 0, tzinfo=timezone.utc)
_KEY = "pk-lf-public:sk-lf-secret"


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class _FakeObservations:
    """GET /api/public/v2/observations as the server answers it: filter JSON, startTime DESC, opaque cursor."""

    def __init__(self, page_size: int | None = None) -> None:
        self.rows: list[dict] = []
        self.requests: list[httpx.Request] = []
        self.failure: str | None = None
        self.page_size = page_size  # None: honour the request's limit
        self.empty_first_page = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.failure == "unreachable":
            raise httpx.ConnectError("connection refused", request=request)
        if self.failure in ("auth", "server", "malformed"):
            return httpx.Response({"auth": 401, "server": 500, "malformed": 200}[self.failure], content=b"<html/>")
        assert request.url.path == "/api/public/v2/observations"
        params = request.url.params
        rows = [row for row in self.rows if all(self._matches(row, condition) for condition in json.loads(params["filter"]))]
        rows.sort(key=lambda row: (datetime.fromisoformat(row["startTime"]), row["id"]), reverse=True)
        offset = int(base64.b64decode(params["cursor"])) if "cursor" in params else 0
        if self.empty_first_page and offset == 0 and "cursor" not in params:
            body = {"data": [], "meta": {"cursor": base64.b64encode(b"0").decode()}}
        else:
            size = self.page_size or int(params["limit"])
            page = rows[offset : offset + size]
            more = offset + size < len(rows)
            body = {"data": page, "meta": {"cursor": base64.b64encode(str(offset + size).encode()).decode() if more else None}}
        parse_obj_as(ObservationsV2Response, body)  # the vendor's own model accepts the shape
        return httpx.Response(200, json=body)

    @staticmethod
    def _matches(row: dict, condition: dict) -> bool:
        value = row.get(condition["column"])
        if condition["type"] == "datetime":
            # The server compares JS Dates: the bound holds milliseconds only.
            bound, actual = datetime.fromisoformat(condition["value"]), datetime.fromisoformat(value)
            return {">=": actual >= bound, "<": actual < bound}[condition["operator"]]
        assert condition["operator"] == "="
        return value == condition["value"]


def _observation(gateway: LangfuseGateway, usage: ModelUsage, **overrides) -> dict:
    """An ObservationV2 as the gateway would have recorded ``usage``."""
    usage_details = {"input": usage.input_tokens, "output": usage.output_tokens}
    if usage.cached_input_tokens is not None:
        usage_details["input_cached_tokens"] = usage.cached_input_tokens
    observation = {
        "id": usage.row_id,
        "traceId": f"trace-{usage.row_id}",
        "projectId": "project",
        "type": "GENERATION",
        "startTime": _iso(usage.timestamp),
        "userId": None if usage.user_id is None else gateway.gateway_user_id(usage.user_id),
        "sessionId": None if usage.session_id is None else gateway.gateway_user_id(usage.session_id),
        "providedModelName": usage.model,
        "usageDetails": {key: value for key, value in usage_details.items() if value is not None},
        "totalCost": None if usage.provider_cost is None else float(usage.provider_cost),
        "tags": [f"ak-agent:{gateway.gateway_user_id(usage.agent_id)}"] if usage.agent_id else [],
        # As the gateway writes it into langfuse-metadata, which Langfuse records as observation metadata.
        "metadata": {"request_id": gateway._metadata_value(gateway.gateway_user_id(usage.request_id))} if usage.request_id else {},
    }
    return observation | overrides


def _usage(row_id: str, at: datetime, **overrides) -> ModelUsage:
    values = {
        "user_id": "alice",
        "agent_id": None,
        "session_id": None,
        "request_id": None,
        "provider": None,
        "model": "gpt-4o",
        "input_tokens": 10,
        "output_tokens": 5,
        "cached_input_tokens": None,
        "provider_cost": Decimal("0.001"),
        "billed_cost": None,
        "currency": "USD",
        "timestamp": at,
        "row_id": row_id,
    }
    return ModelUsage(**(values | overrides))


def _gateway(backend: _FakeObservations | None = None, admin_key: str | None = _KEY, secrets=None) -> LangfuseGateway:
    if secrets is None:
        secrets = MagicMock()
        secrets.get.return_value = None
        secrets.describe.return_value = "cost.gateway.admin_key or the COST_GATEWAY_ADMIN_KEY environment variable"
    config = _CostGatewayConfig(type="langfuse", base_url="https://cloud.langfuse.com/", admin_key=admin_key or "")
    gateway = LangfuseGateway(config, secrets, transport=httpx.MockTransport((backend or _FakeObservations()).handle))
    gateway.fake = backend  # type: ignore[attr-defined]
    return gateway


def _seed(gateway: LangfuseGateway, *usages: ModelUsage, **overrides) -> None:
    gateway.fake.rows += [_observation(gateway, usage, **overrides) for usage in usages]  # type: ignore[attr-defined]


class TestLangfuseContract(LLMGatewayContract):
    page_size = 1000

    @pytest.fixture
    def gateway(self) -> LangfuseGateway:
        return _gateway(_FakeObservations())

    def seed(self, gateway, rows):
        _seed(gateway, *rows)

    def fail(self, gateway, mode):
        gateway.fake.failure = mode


class TestVendorShapes:
    def test_query_parameters_are_the_sdks(self):
        source = inspect.getsource(AsyncRawObservationsClient.get_many)
        vendor_params = set(re.findall(r'"(\w+)":', source))

        assert {"fields", "limit", "cursor", "filter"} <= vendor_params

    @pytest.mark.asyncio
    async def test_the_request(self):
        backend = _FakeObservations()
        await _gateway(backend).fetch_usage(UsageQuery(user_id="alice", session_id="s-1", model="gpt-4o", start=_T0, end=_T0 + timedelta(hours=1)))

        request = backend.requests[0]
        assert request.headers["Authorization"] == "Basic " + base64.b64encode(_KEY.encode()).decode()
        assert request.url.params["fields"] == "core,basic,usage,model,metadata,trace_context"
        assert request.url.params["limit"] == "1000"
        assert json.loads(request.url.params["filter"]) == [
            {"type": "string", "column": "type", "operator": "=", "value": "GENERATION"},
            {"type": "datetime", "column": "startTime", "operator": ">=", "value": "2026-01-05T12:00:00.000Z"},
            {"type": "datetime", "column": "startTime", "operator": "<", "value": "2026-01-05T13:00:00.000Z"},
            {"type": "string", "column": "userId", "operator": "=", "value": "alice"},
            {"type": "string", "column": "sessionId", "operator": "=", "value": "s-1"},
            {"type": "string", "column": "providedModelName", "operator": "=", "value": "gpt-4o"},
        ]


class TestHeaders:
    def test_names_and_formats(self):
        gateway = _gateway()

        headers = gateway.attribution_headers(Attribution(user_id="alice", agent_id="support", session_id="s-1", request_id="req:1"))

        assert headers == {
            "langfuse-user-id": "alice",
            "langfuse-session-id": "s-1",
            "langfuse-tags": "ak-agent:support",
            "langfuse-metadata": "request_id:ak~req%3A1,agent_id:support",  # a colon would split the pair
        }

    def test_awkward_ids_are_encoded_and_none_omitted(self):
        gateway = _gateway()

        headers = gateway.attribution_headers(Attribution(user_id="ü,\r\n", agent_id="a,b"))

        assert headers["langfuse-user-id"] == gateway.gateway_user_id("ü,\r\n")
        assert headers["langfuse-metadata"].count(",") == 0 and "langfuse-session-id" not in headers

    def test_a_value_over_1_kib_raises(self):
        with pytest.raises(ValueError, match="langfuse header limits exceeded: \\['langfuse-user-id'\\]"):
            _gateway().attribution_headers(Attribution(user_id="u" * 1025))

    def test_exactly_1_kib_passes_and_the_error_never_echoes_the_value(self):
        gateway = _gateway()
        assert gateway.attribution_headers(Attribution(user_id="u" * 1024))["langfuse-user-id"] == "u" * 1024

        with pytest.raises(ValueError) as caught:
            gateway.attribution_headers(Attribution(user_id="u" * 1000, session_id="secret-" + "s" * 1020))
        assert "secret-" not in str(caught.value) and "langfuse-session-id" in str(caught.value)

    def test_model_base_url(self):
        gateway = _gateway()

        assert gateway.model_base_url("anthropic/claude-sonnet-4-5") == "https://cloud.langfuse.com/anthropic/v1"
        assert gateway.model_base_url("openai/gpt-4o") == "https://cloud.langfuse.com/openai/v1"
        assert gateway.model_base_url("gpt-4o") == "https://cloud.langfuse.com/openai/v1"


class TestReads:
    @pytest.mark.asyncio
    async def test_an_empty_page_with_a_cursor_is_not_the_end(self):
        backend = _FakeObservations()
        backend.empty_first_page = True
        gateway = _gateway(backend)
        _seed(gateway, _usage("r1", _T0))

        result = await gateway.fetch_usage(UsageQuery(user_id="alice", start=_T0, end=_T0 + timedelta(seconds=1)))

        assert [row.row_id for row in result.rows] == ["r1"]
        assert len(backend.requests) == 2

    @pytest.mark.asyncio
    async def test_newest_first_pages_come_back_oldest_first(self):
        backend = _FakeObservations(page_size=2)
        gateway = _gateway(backend)
        _seed(gateway, *[_usage(f"r{n}", _T0 + timedelta(seconds=n)) for n in range(5)])

        result = await gateway.fetch_usage(UsageQuery(user_id="alice", start=_T0, end=_T0 + timedelta(minutes=1)))

        assert [row.row_id for row in result.rows] == ["r0", "r1", "r2", "r3", "r4"]
        assert len(backend.requests) == 3

    @pytest.mark.asyncio
    async def test_bounds_are_exact_below_the_millisecond(self):
        gateway = _gateway(_FakeObservations())
        start, end = _T0 + timedelta(microseconds=600), _T0 + timedelta(microseconds=2600)
        _seed(
            gateway,
            _usage("before-start", _T0 + timedelta(microseconds=300)),  # in start's millisecond, before start
            _usage("inside", _T0 + timedelta(microseconds=1000)),
            _usage("just-before-end", _T0 + timedelta(microseconds=2300)),  # needs the upper bound ceiled
            _usage("past-end", _T0 + timedelta(microseconds=2800)),  # in end's millisecond, after end
        )

        result = await gateway.fetch_usage(UsageQuery(user_id="alice", start=start, end=end))

        assert [row.row_id for row in result.rows] == ["inside", "just-before-end"]

    @pytest.mark.asyncio
    async def test_only_generations_are_model_calls(self):
        gateway = _gateway(_FakeObservations())
        _seed(gateway, _usage("generation", _T0))
        _seed(gateway, _usage("span", _T0), type="SPAN", totalCost=None)

        result = await gateway.fetch_usage(UsageQuery(user_id="alice", start=_T0, end=_T0 + timedelta(seconds=1)))

        assert [row.row_id for row in result.rows] == ["generation"]

    @pytest.mark.asyncio
    async def test_the_full_mapping(self):
        gateway = _gateway(_FakeObservations())
        # A Slack-style request id: its colons must survive the key:value metadata header.
        expected = _usage(
            "r1",
            _T0,
            user_id="ü,user",
            agent_id="billing,refunds",
            session_id="s\n1",
            request_id="slack:T123:C456:1700000000.123",
            cached_input_tokens=4,
        )
        _seed(gateway, expected)

        (row,) = (await gateway.fetch_usage(UsageQuery(user_id="ü,user", start=_T0, end=_T0 + timedelta(seconds=1)))).rows

        assert row == expected

    @pytest.mark.asyncio
    @pytest.mark.parametrize("key", ["input_cached_tokens", "cache_read_input_tokens", "input_cache_read"])
    async def test_cached_tokens_from_each_known_key(self, key):
        gateway = _gateway(_FakeObservations())
        _seed(gateway, _usage("r1", _T0), usageDetails={"input": 10, "output": 5, key: 7})

        (row,) = (await gateway.fetch_usage(UsageQuery(user_id="alice", start=_T0, end=_T0 + timedelta(seconds=1)))).rows

        assert row.cached_input_tokens == 7

    @pytest.mark.asyncio
    async def test_no_cost_is_unpriced(self):
        gateway = _gateway(_FakeObservations())
        _seed(gateway, _usage("r1", _T0, provider_cost=None))

        total = await gateway.total_spend("alice", UsageWindow(start=_T0, end=_T0 + timedelta(hours=1)))

        assert total.by_model["/gpt-4o"].unpriced_requests == 1

    @pytest.mark.asyncio
    async def test_since_returns_the_oldest_page_first(self):
        gateway = _gateway(_FakeObservations())
        _seed(gateway, *[_usage(f"r{n:04d}", _T0 + timedelta(milliseconds=n)) for n in range(1500)])

        rows, cursor, caught_up = await gateway.fetch_usage_since("alice", None, _T0 + timedelta(minutes=1))

        assert [row.row_id for row in rows] == [f"r{n:04d}" for n in range(1000)]
        assert cursor == SpendCursor(timestamp=_T0 + timedelta(milliseconds=999), ids_at_timestamp=frozenset({"r0999"}))
        assert caught_up is False


class TestAuthAndFactory:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("admin_key", [None, "sk-lf-only-a-secret"])
    async def test_an_unusable_admin_key_is_a_config_error(self, admin_key):
        backend = _FakeObservations()

        with pytest.raises(AKConfigError, match="COST_GATEWAY_ADMIN_KEY"):
            await _gateway(backend, admin_key=admin_key).fetch_usage(UsageQuery(user_id="alice", start=_T0, end=_T0 + timedelta(seconds=1)))
        assert backend.requests == []

    def test_the_factory_builds_it(self, monkeypatch):
        monkeypatch.setattr(SecretManager, "current", classmethod(lambda cls: MagicMock()))

        gateway = LLMGatewayFactory.create(_CostGatewayConfig(type="langfuse", base_url="https://cloud.langfuse.com"))

        assert isinstance(gateway, LangfuseGateway)

    def test_a_missing_extra_names_it(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "agentkernel.cost.gateway.langfuse", None)

        with pytest.raises(ImportError, match="'cost' extra"):
            LLMGatewayFactory.create(_CostGatewayConfig(type="langfuse", base_url="https://cloud.langfuse.com"))

    def test_it_never_recognises_a_budget_refusal(self):
        assert _gateway().is_budget_refusal(Exception("ExceededBudget: budget_exceeded")) is False
