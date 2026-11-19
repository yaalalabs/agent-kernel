"""LiteLLMGateway (spec §5.1): capabilities per mode, attribution headers, budget-refusal recognition, usage reads over
a fake /spend/logs/v2, the LLMGatewayContract, and the factory branch."""

import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import httpx
import openai
import pytest

from agentkernel.core.config import _CostGatewayConfig
from agentkernel.core.util.factory import AKConfigError
from agentkernel.cost import (
    Attribution,
    BudgetLimit,
    BudgetPeriod,
    GatewayCapabilities,
    GatewayFilter,
    LLMGatewayFactory,
    UnsupportedCapabilityError,
    UsageQuery,
    UsageRetrievalError,
    UsageTruncatedError,
)
from agentkernel.cost.gateway.litellm import LiteLLMGateway
from agentkernel.cost.testing import LLMGatewayContract
from agentkernel.secret import SecretManager

_BUDGET_BODY = {"error": {"message": "Budget has been exceeded!", "type": "budget_exceeded", "param": None, "code": "429"}}


def _gateway(api: str = "end_user") -> LiteLLMGateway:
    litellm = {"api": api, "customer_org_alias": "acme"} if api == "customer_management" else {"api": api}
    return LiteLLMGateway(_CostGatewayConfig(type="litellm", base_url="https://litellm.test", litellm=litellm), MagicMock())


def _openai_error(status: int, body: dict) -> openai.APIStatusError:
    """Built the way the OpenAI SDK builds it: the body attribute is the inner "error" object."""
    response = httpx.Response(status, json=body, request=httpx.Request("POST", "https://litellm.test/chat/completions"))
    return openai.RateLimitError(f"Error code: {status} - {body}", response=response, body=body.get("error", body))


class TestCapabilities:
    def test_end_user(self):
        assert _gateway("end_user").capabilities == GatewayCapabilities(
            usage_retrieval=True,
            cost_retrieval=True,
            user_aggregation=True,
            agent_aggregation=True,
            custom_metadata=True,
            native_user_budget=True,
            request_level_budget_check=True,
            streaming_usage=True,
            filters=frozenset({GatewayFilter.USER, GatewayFilter.TIME_RANGE, GatewayFilter.MODEL}),
            row_cap=10_000,
        )

    def test_customer_management(self):
        assert _gateway("customer_management").capabilities == GatewayCapabilities(
            custom_metadata=True, request_level_budget_check=True, streaming_usage=True  # budget sync deferred
        )

    def test_the_mode_is_per_instance(self):
        _gateway("customer_management")

        assert _gateway("end_user").capabilities.usage_retrieval is True


class TestAttributionHeaders:
    _FULL = Attribution(user_id="alice", agent_id="support", session_id="s-1", request_id="r-1")

    def test_end_user(self):
        assert _gateway().attribution_headers(self._FULL) == {
            "x-litellm-customer-id": "alice",
            "x-litellm-tags": "ak-agent:support",
            "x-litellm-spend-logs-metadata": json.dumps({"ak_session_id": "s-1", "ak_request_id": "r-1", "ak_agent_id": "support"}),
        }

    def test_customer_management(self):
        headers = _gateway("customer_management").attribution_headers(self._FULL)

        assert headers["x-litellm-customer-org-alias"] == "acme"
        assert headers["x-litellm-customer-member-id"] == "alice"
        assert "x-litellm-customer-id" not in headers
        assert headers["x-litellm-tags"] == "ak-agent:support"

    @pytest.mark.parametrize("api", ["end_user", "customer_management"])
    def test_none_fields_are_omitted(self, api):
        headers = _gateway(api).attribution_headers(Attribution(user_id=None, agent_id="support"))

        assert set(headers) == {"x-litellm-tags", "x-litellm-spend-logs-metadata"}
        assert json.loads(headers["x-litellm-spend-logs-metadata"]) == {"ak_agent_id": "support"}

    def test_nothing_set_sends_nothing(self):
        assert _gateway().attribution_headers(Attribution(user_id=None)) == {}

    @pytest.mark.parametrize("agent", ["billing,refunds", "line\r\nbreak"])
    def test_an_awkward_agent_name_is_encoded_in_tags(self, agent):
        gateway = _gateway()

        tags = gateway.attribution_headers(Attribution(user_id=None, agent_id=agent))["x-litellm-tags"]

        assert "," not in tags and "\r" not in tags and "\n" not in tags
        assert gateway.raw_user_id(tags.removeprefix("ak-agent:")) == agent

    def test_awkward_ids_round_trip_through_metadata(self):
        attribution = Attribution(user_id="ü\r\n", agent_id="a,b", session_id="séance\n", request_id="r")

        value = _gateway().attribution_headers(attribution)["x-litellm-spend-logs-metadata"]

        assert value.isascii() and "\r" not in value and "\n" not in value
        assert json.loads(value) == {"ak_session_id": "séance\n", "ak_request_id": "r", "ak_agent_id": "a,b"}


class TestIsBudgetRefusal:
    def test_an_openai_sdk_error_carrying_the_inner_body(self):
        assert _gateway().is_budget_refusal(_openai_error(429, _BUDGET_BODY)) is True

    def test_a_full_body_attribute(self):
        error = Exception("refused")
        error.body = _BUDGET_BODY  # type: ignore[attr-defined]

        assert _gateway().is_budget_refusal(error) is True

    def test_litellm_error_type_at_the_top_level(self):
        error = Exception("refused")
        error.body = {"litellm_error_type": "budget_exceeded"}  # type: ignore[attr-defined]

        assert _gateway().is_budget_refusal(error) is True

    def test_the_response_body_without_a_body_attribute(self):
        error = Exception("refused")
        error.response = httpx.Response(400, json=_BUDGET_BODY)  # type: ignore[attr-defined]

        assert _gateway().is_budget_refusal(error) is True

    def test_the_message_without_any_body(self):
        error = Exception("litellm.BudgetExceededError: ExceededBudget: End User=alice over budget. Spend=1.2, Budget=1.0 (budget_exceeded)")

        assert _gateway().is_budget_refusal(error) is True

    def test_never_a_bare_429(self):
        class RateLimited(Exception):
            status_code = 429

        assert _gateway().is_budget_refusal(RateLimited("Too Many Requests")) is False

    def test_not_a_plain_rate_limit_from_the_sdk(self):
        body = {"error": {"message": "slow down", "type": "rate_limit_exceeded", "code": "429"}}

        assert _gateway().is_budget_refusal(_openai_error(429, body)) is False

    @pytest.mark.parametrize("message", ["ExceededBudget: over", "budget_exceeded somewhere"])
    def test_the_message_needs_both_markers(self, message):
        assert _gateway().is_budget_refusal(Exception(message)) is False

    def test_a_body_that_does_not_match_wins_over_the_message(self):
        error = Exception("ExceededBudget: budget_exceeded")
        error.body = {"type": "rate_limit_exceeded"}  # type: ignore[attr-defined]

        assert _gateway().is_budget_refusal(error) is False

    def test_a_response_that_is_not_json(self):
        error = Exception("refused")
        error.response = httpx.Response(429, content=b"<html>busy</html>")  # type: ignore[attr-defined]

        assert _gateway().is_budget_refusal(error) is False


class TestFactory:
    @pytest.mark.parametrize("type_", ["litellm", "LiteLLM"])
    def test_builds_the_gateway(self, monkeypatch, type_):
        monkeypatch.setattr(SecretManager, "current", classmethod(lambda cls: MagicMock()))

        gateway = LLMGatewayFactory.create(_CostGatewayConfig(type=type_, base_url="https://litellm.test"))

        assert isinstance(gateway, LiteLLMGateway)

    def test_a_missing_extra_names_it(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "agentkernel.cost.gateway.litellm", None)

        with pytest.raises(ImportError, match="'cost' extra"):
            LLMGatewayFactory.create(_CostGatewayConfig(type="litellm", base_url="https://litellm.test"))


# Usage reads


_T0 = datetime(2026, 1, 5, 12, 0, 0, tzinfo=timezone.utc)


class _FakeSpendLogs:
    """/spend/logs/v2 as the 1.105 proxy serves it: second-granular inclusive bounds, startTime ascending, the count cap."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.requests: list[httpx.Request] = []
        self.failure: str | None = None
        self.override: dict | None = None  # a fixed /spend/logs/v2 body to return instead
        self.budgets: dict[str, dict] = {}
        self.customers: dict[str, dict] = {}
        self.posts: list[tuple[str, dict]] = []
        self.forced: dict[str, httpx.Response] = {}  # path -> a fixed response
        self.version: str | None = "1.111.0"

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.failure == "unreachable":
            raise httpx.ConnectError("connection refused", request=request)
        if self.failure in ("auth", "server", "malformed"):
            return httpx.Response({"auth": 401, "server": 500, "malformed": 200}[self.failure], content=b"<html/>")
        path = request.url.path
        if path in self.forced:
            return self.forced[path]
        if request.method == "POST":
            return self._admin(path, json.loads(request.content))
        if path == "/health/readiness":
            return httpx.Response(200, json={"status": "healthy", "db": "connected", "litellm_version": self.version})
        if self.override is not None:
            return httpx.Response(200, json=self.override)
        assert path == "/spend/logs/v2"
        params = request.url.params
        rows = [
            row
            for row in self.rows
            # As the 1.105.7 proxy does: both dates parsed as whole-second UTC instants, compared to full timestamps.
            if self._instant(params["start_date"]) <= datetime.fromisoformat(row["startTime"]) <= self._instant(params["end_date"])
            and ("end_user" not in params or row["end_user"] == params["end_user"])
            and ("model" not in params or row["model"] == params["model"])
        ]
        rows.sort(key=lambda row: (datetime.fromisoformat(row["startTime"]), row["request_id"]))
        page, size = int(params["page"]), int(params["page_size"])
        total = min(len(rows), 10_000)
        return httpx.Response(
            200,
            json={
                "data": rows[(page - 1) * size : page * size],
                "total": total,
                "page": page,
                "page_size": size,
                "total_pages": (total + size - 1) // size,
                "total_is_capped": len(rows) > 10_000,
            },
        )

    @staticmethod
    def _instant(value: str) -> datetime:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)

    def _admin(self, path: str, body: dict) -> httpx.Response:
        """The budget and customer routes, with the 1.105 proxy's "already exists" replies."""
        self.posts.append((path, body))
        table, key = (self.budgets, "budget_id") if path.startswith("/budget/") else (self.customers, "user_id")
        if path.endswith("/new"):
            if body[key] in table:
                if table is self.budgets:  # an HTTPException
                    return httpx.Response(400, json={"detail": {"error": f"Budget with id '{body[key]}' already exists."}})
                message = f"Customer already exists, passed user_id={body[key]}. Please pass a new user_id."
                return httpx.Response(400, json={"error": {"message": message, "type": "bad_request", "param": "user_id", "code": "400"}})
            table[body[key]] = dict(body)
        else:
            table[body[key]].update(body)
        return httpx.Response(200, json=table[body[key]])


def _log(gateway: LiteLLMGateway, row_id: str, at: datetime, user: str = "alice", **overrides) -> dict:
    """One spend-log row in the proxy's shape."""
    row = {
        "request_id": row_id,
        "startTime": at.isoformat(),
        "end_user": gateway.gateway_user_id(user),
        "custom_llm_provider": "openai",
        "model": "gpt-4o",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "spend": 0.001,
        "request_tags": [],
        "metadata": {"spend_logs_metadata": {}, "usage_object": {}},
    }
    row.update(overrides)
    return row


def _reading_gateway(backend: _FakeSpendLogs, api: str = "end_user", secrets=None, **config) -> LiteLLMGateway:
    litellm = {"api": api, "customer_org_alias": "acme"} if api == "customer_management" else {"api": api}
    if secrets is None:
        secrets = MagicMock()
        secrets.get.return_value = None
    return LiteLLMGateway(
        _CostGatewayConfig(type="litellm", base_url="https://litellm.test", litellm=litellm, **config),
        secrets,
        transport=httpx.MockTransport(backend.handle),
    )


def _query(**overrides) -> UsageQuery:
    return UsageQuery(**{"user_id": "alice", "start": _T0 - timedelta(hours=1), "end": _T0 + timedelta(hours=1), **overrides})


class TestLiteLLMEndUserContract(LLMGatewayContract):
    page_size = 1000

    @pytest.fixture
    def gateway(self) -> LiteLLMGateway:
        backend = _FakeSpendLogs()
        gateway = _reading_gateway(backend)
        gateway.fake = backend  # type: ignore[attr-defined]
        return gateway

    def seed(self, gateway, rows):
        backend = gateway.fake
        for row in rows:
            logged = {"ak_session_id": row.session_id, "ak_request_id": row.request_id}
            backend.rows.append(
                _log(
                    gateway,
                    row.row_id,
                    row.timestamp,
                    user=row.user_id,
                    custom_llm_provider=row.provider,
                    model=row.model,
                    prompt_tokens=row.input_tokens,
                    completion_tokens=row.output_tokens,
                    spend=None if row.provider_cost is None else str(row.provider_cost),
                    request_tags=[f"ak-agent:{gateway.gateway_user_id(row.agent_id)}"] if row.agent_id else [],
                    metadata={
                        "spend_logs_metadata": {k: v for k, v in logged.items() if v is not None},
                        "usage_object": {"prompt_tokens_details": {"cached_tokens": row.cached_input_tokens}},
                    },
                )
            )

    def fail(self, gateway, mode):
        gateway.fake.failure = mode


class TestFetchUsage:
    @pytest.mark.asyncio
    async def test_rows_later_in_the_end_second_are_read(self):
        """The proxy drops rows after the end_date instant; sending the floored end lost 12:00:00.400 for 12:00:00.700."""
        backend = _FakeSpendLogs()
        gateway = _reading_gateway(backend)
        backend.rows = [_log(gateway, "r1", _T0 + timedelta(milliseconds=400)), _log(gateway, "late", _T0 + timedelta(milliseconds=800))]
        end = _T0 + timedelta(milliseconds=700)

        result = await gateway.fetch_usage(_query(start=_T0 - timedelta(seconds=1), end=end))
        rows, cursor, caught_up = await gateway.fetch_usage_since("alice", None, end)

        assert [row.row_id for row in result.rows] == ["r1"]
        assert [row.row_id for row in rows] == ["r1"] and caught_up is True
        assert cursor.timestamp == _T0 + timedelta(milliseconds=400)

    @pytest.mark.asyncio
    async def test_request_shape(self):
        backend = _FakeSpendLogs()
        gateway = _reading_gateway(backend, admin_key="sk-admin")

        await gateway.fetch_usage(_query(start=_T0 + timedelta(microseconds=900_000), end=_T0 + timedelta(seconds=5), model="gpt-4o"))

        request = backend.requests[0]
        assert dict(request.url.params) == {
            "start_date": "2026-01-05 12:00:00",
            "end_date": "2026-01-05 12:00:06",  # the next second: the proxy compares full timestamps to it
            "page": "1",
            "page_size": "1000",
            "sort_by": "startTime",
            "sort_order": "asc",
            "end_user": "alice",
            "model": "gpt-4o",
        }
        assert request.headers["Authorization"] == "Bearer sk-admin"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("config", "secret_values", "expected"),
        [
            ({"admin_key": "sk-admin", "api_key": "sk-api"}, {}, "Bearer sk-admin"),
            ({"api_key": "sk-api"}, {"COST_GATEWAY_ADMIN_KEY": "sk-admin-secret"}, "Bearer sk-admin-secret"),
            ({}, {"COST_GATEWAY_API_KEY": "sk-api-secret"}, "Bearer sk-api-secret"),
            ({}, {}, None),
        ],
    )
    async def test_the_admin_key_falls_back_to_the_api_key(self, config, secret_values, expected):
        backend = _FakeSpendLogs()
        secrets = MagicMock()
        secrets.get.side_effect = lambda key, default=None: secret_values.get(key, default)

        await _reading_gateway(backend, secrets=secrets, **config).fetch_usage(_query())

        assert backend.requests[0].headers.get("Authorization") == expected

    @pytest.mark.asyncio
    async def test_pages_until_the_total_is_read(self):
        backend = _FakeSpendLogs()
        gateway = _reading_gateway(backend)
        backend.rows = [_log(gateway, f"r{n:05d}", _T0 + timedelta(milliseconds=n)) for n in range(2500)]

        result = await gateway.fetch_usage(_query())

        assert [row.row_id for row in result.rows] == [f"r{n:05d}" for n in range(2500)]
        assert [request.url.params["page"] for request in backend.requests] == ["1", "2", "3"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("body", [{"data": [], "total": 10_000}, {"data": [], "total": 9_999, "total_is_capped": True}])
    async def test_the_row_cap_is_truncation(self, body):
        backend = _FakeSpendLogs()
        backend.override = body

        with pytest.raises(UsageTruncatedError):
            await _reading_gateway(backend).fetch_usage(_query())

    @pytest.mark.asyncio
    async def test_the_window_is_exact_on_the_client(self):
        backend = _FakeSpendLogs()
        gateway = _reading_gateway(backend)
        start, end = _T0 + timedelta(microseconds=500_000), _T0 + timedelta(seconds=2)
        backend.rows = [
            _log(gateway, "before-start", _T0 + timedelta(microseconds=100_000)),  # in start's second
            _log(gateway, "at-start", start),
            _log(gateway, "at-end", end),  # the next window's
        ]

        result = await gateway.fetch_usage(_query(start=start, end=end))

        assert [row.row_id for row in result.rows] == ["at-start"]

    @pytest.mark.asyncio
    async def test_a_body_without_data_is_a_retrieval_error(self):
        backend = _FakeSpendLogs()
        backend.override = {"detail": "nope"}

        with pytest.raises(UsageRetrievalError):
            await _reading_gateway(backend).fetch_usage(_query())

    @pytest.mark.asyncio
    async def test_a_row_that_does_not_map_fails_the_read(self):
        backend = _FakeSpendLogs()
        backend.override = {"data": [{"request_id": "r1"}], "total": 1}  # no startTime

        with pytest.raises(UsageRetrievalError):
            await _reading_gateway(backend).fetch_usage(_query())


class TestRowMapping:
    @staticmethod
    async def _one(row_overrides: dict, **query) -> object:
        backend = _FakeSpendLogs()
        gateway = _reading_gateway(backend)
        row = _log(gateway, "r1", _T0)
        row.update(row_overrides)
        backend.override = {"data": [row], "total": 1}
        (only,) = (await gateway.fetch_usage(_query(**query))).rows
        return only

    @pytest.mark.asyncio
    async def test_the_full_mapping(self):
        gateway = _reading_gateway(_FakeSpendLogs())
        row = await self._one(
            {
                "end_user": gateway.gateway_user_id("ü,user"),
                "request_tags": ["other", f"ak-agent:{gateway.gateway_user_id('billing,refunds')}"],
                "metadata": {
                    "spend_logs_metadata": {"ak_session_id": "s-1", "ak_request_id": "q-1"},
                    "usage_object": {"prompt_tokens_details": {"cached_tokens": 4}},
                },
            },
            user_id="ü,user",
        )

        assert (row.user_id, row.agent_id, row.session_id, row.request_id) == ("ü,user", "billing,refunds", "s-1", "q-1")
        assert (row.provider, row.model, row.input_tokens, row.output_tokens, row.cached_input_tokens) == ("openai", "gpt-4o", 10, 5, 4)
        assert row.provider_cost == Decimal("0.001") and row.currency == "USD" and row.row_id == "r1"

    @pytest.mark.asyncio
    async def test_missing_values_stay_unknown(self):
        row = await self._one({"prompt_tokens": None, "completion_tokens": None, "spend": None, "metadata": None, "request_tags": None})

        assert (row.input_tokens, row.output_tokens, row.cached_input_tokens, row.provider_cost) == (None, None, None, None)
        assert (row.agent_id, row.session_id) == (None, None)

    @pytest.mark.asyncio
    async def test_a_zero_spend_stays_zero(self):
        assert (await self._one({"spend": 0})).provider_cost == Decimal(0)

    @pytest.mark.asyncio
    async def test_json_string_columns_from_older_proxies(self):
        row = await self._one(
            {
                "request_tags": json.dumps(["ak-agent:support"]),
                "metadata": json.dumps({"spend_logs_metadata": json.dumps({"ak_session_id": "s-1"})}),
            }
        )

        assert (row.agent_id, row.session_id) == ("support", "s-1")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("stamp", ["2026-01-05T12:00:00.250000", "2026-01-05T12:00:00.25Z", "2026-01-05T14:00:00.25+02:00"])
    async def test_timestamps_come_back_in_utc(self, stamp):
        row = await self._one({"startTime": stamp})

        assert row.timestamp == _T0 + timedelta(milliseconds=250)
        assert row.timestamp.tzinfo == timezone.utc


class TestLiteLLMCustomerManagementContract(LLMGatewayContract):
    """Declares no reads and no budget sync, so only the header and "undeclared raises" cases apply."""

    @pytest.fixture
    def gateway(self) -> LiteLLMGateway:
        return _reading_gateway(_FakeSpendLogs(), api="customer_management")


class TestCustomerManagementReads:
    @pytest.mark.asyncio
    async def test_usage_reads_are_unsupported(self):
        gateway = _reading_gateway(_FakeSpendLogs(), api="customer_management")

        with pytest.raises(UnsupportedCapabilityError):
            await gateway.fetch_usage(_query())
        with pytest.raises(UnsupportedCapabilityError):
            await gateway.fetch_usage_since("alice", None, _T0)


# Native budgets and the probe


_MONTHLY_10 = BudgetLimit(amount=Decimal("10"))


def _admin_gateway(backend: _FakeSpendLogs, **config) -> LiteLLMGateway:
    return _reading_gateway(backend, **({"admin_key": "sk-admin"} | config))


class TestBudgetId:
    def test_equal_amounts_share_a_row(self):
        assert LiteLLMGateway.budget_id(BudgetLimit(amount=Decimal("10.00"))) == LiteLLMGateway.budget_id(_MONTHLY_10)

    @pytest.mark.parametrize(
        "other",
        [
            BudgetLimit(amount=Decimal("10.5")),
            BudgetLimit(amount=Decimal("10"), period=BudgetPeriod.WEEKLY),
            BudgetLimit(amount=Decimal("10"), currency="EUR"),
        ],
    )
    def test_each_dimension_changes_it(self, other):
        assert LiteLLMGateway.budget_id(other) != LiteLLMGateway.budget_id(_MONTHLY_10)

    def test_shape(self):
        budget_id = LiteLLMGateway.budget_id(_MONTHLY_10)

        assert budget_id.startswith("ak-") and len(budget_id) == 19 and int(budget_id[3:], 16) >= 0


class TestSyncBudgetDefinitions:
    @pytest.mark.asyncio
    async def test_creates_each_distinct_budget_once(self):
        backend = _FakeSpendLogs()
        weekly = BudgetLimit(amount=Decimal("2.5"), period=BudgetPeriod.WEEKLY)

        await _admin_gateway(backend).sync_budget_definitions([_MONTHLY_10, BudgetLimit(amount=Decimal("10.00")), weekly])

        assert backend.posts == [
            ("/budget/new", {"budget_id": LiteLLMGateway.budget_id(_MONTHLY_10), "max_budget": 10.0, "budget_duration": "1mo"}),
            ("/budget/new", {"budget_id": LiteLLMGateway.budget_id(weekly), "max_budget": 2.5, "budget_duration": "7d"}),
        ]
        assert all(request.headers["Authorization"] == "Bearer sk-admin" for request in backend.requests)

    @pytest.mark.asyncio
    async def test_an_existing_budget_is_updated(self):
        backend = _FakeSpendLogs()
        daily = BudgetLimit(amount=Decimal("1"), period=BudgetPeriod.DAILY)
        gateway = _admin_gateway(backend)
        await gateway.sync_budget_definitions([daily])

        await gateway.sync_budget_definitions([daily])

        assert [path for path, _ in backend.posts] == ["/budget/new", "/budget/new", "/budget/update"]
        assert backend.posts[-1][1]["budget_duration"] == "1d"

    @pytest.mark.asyncio
    async def test_a_non_usd_budget_is_refused_before_any_write(self):
        backend = _FakeSpendLogs()

        with pytest.raises(AKConfigError, match="EUR"):
            await _admin_gateway(backend).sync_budget_definitions([_MONTHLY_10, BudgetLimit(amount=Decimal("10"), currency="EUR")])
        assert backend.posts == []  # the USD budget listed first was not sent either


class TestSyncBudgets:
    @pytest.mark.asyncio
    async def test_customers_are_linked_to_their_budget_row(self):
        backend = _FakeSpendLogs()
        gateway = _admin_gateway(backend)

        await gateway.sync_budgets({"alice": _MONTHLY_10, "ak-system": None})

        assert backend.posts == [
            ("/customer/new", {"user_id": "alice", "budget_id": LiteLLMGateway.budget_id(_MONTHLY_10)}),
            ("/customer/new", {"user_id": "ak-system"}),
        ]

    @pytest.mark.asyncio
    async def test_an_existing_customer_is_updated(self):
        backend = _FakeSpendLogs()
        gateway = _admin_gateway(backend)
        await gateway.sync_budgets({"alice": None})

        await gateway.sync_budgets({"alice": _MONTHLY_10})

        assert [path for path, _ in backend.posts] == ["/customer/new", "/customer/new", "/customer/update"]
        assert backend.customers["alice"]["budget_id"] == LiteLLMGateway.budget_id(_MONTHLY_10)

    @pytest.mark.asyncio
    async def test_awkward_ids_are_sent_encoded(self):
        backend = _FakeSpendLogs()
        gateway = _admin_gateway(backend)

        await gateway.sync_budgets({"ü,\r\nuser": None})

        (sent,) = [body["user_id"] for _, body in backend.posts]
        assert sent == gateway.gateway_user_id("ü,\r\nuser") and sent.isascii() and "," not in sent


class TestBudgetSyncErrors:
    @pytest.mark.asyncio
    async def test_no_admin_key_is_a_config_error_naming_it(self):
        backend = _FakeSpendLogs()
        secrets = MagicMock()
        secrets.get.return_value = None
        secrets.describe.return_value = "cost.gateway.admin_key or the COST_GATEWAY_ADMIN_KEY environment variable"
        gateway = _reading_gateway(backend, secrets=secrets)

        await gateway.sync_budget_definitions([])  # nothing to send: no key needed
        await gateway.sync_budgets({})
        with pytest.raises(AKConfigError, match="COST_GATEWAY_ADMIN_KEY"):
            await gateway.sync_budgets({"alice": None})
        assert backend.requests == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("response", "raised"),
        [
            (httpx.Response(401), UsageRetrievalError),
            (httpx.Response(500), UsageRetrievalError),
            (httpx.Response(422, json={"detail": "budget_duration invalid"}), AKConfigError),
            (httpx.Response(400, json={"detail": {"error": "max_budget must be a non-negative finite number"}}), AKConfigError),
        ],
    )
    async def test_failures(self, response, raised):
        backend = _FakeSpendLogs()
        backend.forced["/budget/new"] = response

        with pytest.raises(raised) as caught:
            await _admin_gateway(backend).sync_budget_definitions([_MONTHLY_10])

        if raised is UsageRetrievalError:
            assert caught.value.auth is (response.status_code == 401)
        else:  # the proxy's response text stays out of a message that startup logs
            assert response.text not in str(caught.value) and "invalid" not in str(caught.value) and "non-negative" not in str(caught.value)
        assert [path for path, _ in backend.posts] == []  # forced responses never reach the tables

    @pytest.mark.asyncio
    async def test_a_failed_update_is_mapped_too(self):
        backend = _FakeSpendLogs()
        gateway = _admin_gateway(backend)
        await gateway.sync_budgets({"alice": None})
        backend.forced["/customer/update"] = httpx.Response(422, json={"detail": "bad"})

        with pytest.raises(AKConfigError, match="/customer/update"):
            await gateway.sync_budgets({"alice": _MONTHLY_10})

    @pytest.mark.asyncio
    async def test_customer_management_does_not_sync(self):
        gateway = _admin_gateway(_FakeSpendLogs(), api="customer_management")

        with pytest.raises(UnsupportedCapabilityError):
            await gateway.sync_budget_definitions([_MONTHLY_10])
        with pytest.raises(UnsupportedCapabilityError):
            await gateway.sync_budgets({"alice": None})


class TestProbe:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("version", ["1.111.0", "1.111.0.dev4", "1.112.3", "2.0.0"])
    async def test_customer_management_accepts_1_111_and_later(self, version):
        backend = _FakeSpendLogs()
        backend.version = version

        await _admin_gateway(backend, api="customer_management").probe()

        assert backend.requests[0].url.path == "/health/readiness"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("version", ["1.110.9", "1.105.7", None, "unknown"])
    async def test_customer_management_refuses_older_or_unknown(self, version):
        backend = _FakeSpendLogs()
        backend.version = version

        with pytest.raises(AKConfigError, match="1.111"):
            await _admin_gateway(backend, api="customer_management").probe()

    @pytest.mark.asyncio
    async def test_an_unready_proxy_is_an_availability_error(self):
        backend = _FakeSpendLogs()
        backend.forced["/health/readiness"] = httpx.Response(503, json={"status": "unhealthy"})

        with pytest.raises(UsageRetrievalError):
            await _admin_gateway(backend, api="customer_management").probe()

    @pytest.mark.asyncio
    async def test_end_user_only_logs_the_timezone_assumption(self, caplog):
        backend = _FakeSpendLogs()
        caplog.set_level(logging.INFO, logger="ak.cost.gateway.litellm")

        await _admin_gateway(backend).probe()

        assert backend.requests == []
        assert "budgets assume UTC" in caplog.text
