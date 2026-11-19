"""The gateway seam (spec §4): LLMGateway's id transform and batch bound, GatewayHTTP, LLMGatewayFactory, and the
LLMGatewayContract suite run against a fake gateway over httpx.MockTransport."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import httpx
import pytest

import agentkernel.cost as cost
from agentkernel.core.config import _CostGatewayConfig
from agentkernel.core.util.factory import AKConfigError
from agentkernel.cost import (
    Attribution,
    GatewayCapabilities,
    GatewayFilter,
    LLMGateway,
    LLMGatewayFactory,
    ModelUsage,
    SpendCursor,
    SpendTotal,
    UsageQuery,
    UsageResult,
    UsageRetrievalError,
    UsageTruncatedError,
    UsageWindow,
)
from agentkernel.cost.gateway.http import GatewayHTTP
from agentkernel.cost.testing import LLMGatewayContract
from agentkernel.secret import SecretManager

_BASE_URL = "https://gw.test"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_T0 = datetime(2026, 1, 5, 12, 0, 0, tzinfo=timezone.utc)


def _second(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


class _FakeBackend:
    """A usage API that filters to the second (inclusive at both ends) and pages by offset, like LiteLLM's."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.failure: str | None = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.failure == "unreachable":
            raise httpx.ConnectError("connection refused", request=request)
        if self.failure in ("auth", "server", "malformed"):
            return httpx.Response({"auth": 401, "server": 503, "malformed": 200}[self.failure], content=b"<html>nope</html>")
        params = request.url.params
        rows = [
            row
            for row in self.rows
            if ("user" not in params or row["user"] == params["user"])
            and params["start"] <= _second(datetime.fromisoformat(row["ts"])) <= params["end"]
        ]
        offset, limit = int(params["offset"]), int(params["limit"])
        return httpx.Response(200, json={"rows": rows[offset : offset + limit], "total": len(rows)})


class _BudgetExceeded(Exception):
    pass


class _FakeGateway(LLMGateway):
    name = "fake"
    capabilities = GatewayCapabilities(usage_retrieval=True, windowed_spend=True, filters=frozenset({GatewayFilter.USER, GatewayFilter.TIME_RANGE}))
    page_size = 3

    def __init__(self, config, secrets, backend: _FakeBackend | None = None):
        super().__init__(config, secrets)
        self.backend = backend or _FakeBackend()
        self.http = GatewayHTTP(self.name, config.base_url, {"Authorization": "Bearer sk-secret"}, transport=httpx.MockTransport(self.backend.handle))

    def attribution_headers(self, attribution: Attribution) -> dict[str, str]:
        ids = {"x-user": attribution.user_id, "x-agent": attribution.agent_id, "x-session": attribution.session_id}
        return {key: self.gateway_user_id(value) for key, value in ids.items() if value is not None}

    def is_budget_refusal(self, error: BaseException) -> bool:
        return isinstance(error, _BudgetExceeded)

    async def _page(self, user_id: str | None, start: datetime, end: datetime, offset: int) -> tuple[list[ModelUsage], int]:
        params: dict = {"start": _second(start), "end": _second(end), "offset": offset, "limit": self.page_size}
        if user_id is not None:
            params["user"] = self.gateway_user_id(user_id)
        body = await self.http.request("GET", "/rows", params=params)
        return [self._map(row) for row in body["rows"]], body["total"]

    def _map(self, row: dict) -> ModelUsage:
        return ModelUsage(
            user_id=self.raw_user_id(row["user"]),
            agent_id=None,
            session_id=None,
            request_id=None,
            provider=row["provider"],
            model=row["model"],
            input_tokens=row["in"],
            output_tokens=row["out"],
            cached_input_tokens=row["cached"],
            provider_cost=None if row["cost"] is None else Decimal(row["cost"]),
            billed_cost=None,
            currency="USD",
            timestamp=datetime.fromisoformat(row["ts"]),
            row_id=row["id"],
        )

    async def fetch_usage(self, query: UsageQuery) -> UsageResult:
        self._require_filters(query)
        rows: list[ModelUsage] = []
        while True:
            page, total = await self._page(query.user_id, query.start, query.end, len(rows))
            rows += page
            if not page or len(rows) >= total:
                return UsageResult(rows=rows)

    async def total_spend(self, user_id: str, window: UsageWindow) -> SpendTotal:
        result = await self.fetch_usage(UsageQuery(user_id=user_id, start=window.start, end=window.end))
        return SpendTotal.from_rows(result.rows, "USD")

    async def fetch_usage_since(self, user_id, cursor, until):
        page, total = await self._page(user_id, cursor.timestamp if cursor else _EPOCH, until, 0)
        return self._next_batch(page, cursor, until, complete=total <= self.page_size)

    async def close(self) -> None:
        await self.http.close()


class _BareGateway(LLMGateway):
    """Declares nothing; only the required methods."""

    name = "bare"

    def attribution_headers(self, attribution: Attribution) -> dict[str, str]:
        return {}

    def is_budget_refusal(self, error: BaseException) -> bool:
        return False


def _config(type_: str = f"{__name__}._FakeGateway") -> _CostGatewayConfig:
    return _CostGatewayConfig(type=type_, base_url=_BASE_URL)


class TestFakeGatewayContract(LLMGatewayContract):
    page_size = _FakeGateway.page_size

    @pytest.fixture
    def gateway(self) -> LLMGateway:
        return _FakeGateway(_config(), MagicMock())

    def seed(self, gateway, rows):
        gateway.backend.rows += [
            {
                "id": row.row_id,
                "user": gateway.gateway_user_id(row.user_id),
                "ts": row.timestamp.isoformat(),
                "provider": row.provider,
                "model": row.model,
                "in": row.input_tokens,
                "out": row.output_tokens,
                "cached": row.cached_input_tokens,
                "cost": None if row.provider_cost is None else str(row.provider_cost),
            }
            for row in rows
        ]
        gateway.backend.rows.sort(key=lambda row: (row["ts"], row["id"]))

    def fail(self, gateway, mode):
        gateway.backend.failure = mode


class TestBareGatewayContract(LLMGatewayContract):
    """Every optional operation of a gateway that declares nothing raises UnsupportedCapabilityError."""

    @pytest.fixture
    def gateway(self) -> LLMGateway:
        return _BareGateway(_config(), MagicMock())


class TestGatewayUserId:
    @pytest.fixture
    def gateway(self):
        return _BareGateway(_config(), MagicMock())

    @pytest.mark.parametrize("value", ["alice", "user@example.com", "auth0|abc 123", ""])
    def test_plain_ids_pass_through(self, gateway, value):
        assert gateway.gateway_user_id(value) == value

    @pytest.mark.parametrize("value", ["a\r\nb", "a,b", "ünï", "tab\there", "ak~%41", "ak~plain"])
    def test_awkward_ids_are_encoded_and_round_trip(self, gateway, value):
        encoded = gateway.gateway_user_id(value)

        assert encoded.startswith("ak~")
        assert encoded.isascii() and encoded.isprintable() and "," not in encoded
        assert gateway.raw_user_id(encoded) == value


def _usage(row_id: str, timestamp: datetime) -> ModelUsage:
    return ModelUsage(
        user_id="u",
        agent_id=None,
        session_id=None,
        request_id=None,
        provider=None,
        model=None,
        input_tokens=None,
        output_tokens=None,
        cached_input_tokens=None,
        provider_cost=None,
        billed_cost=None,
        currency="USD",
        timestamp=timestamp,
        row_id=row_id,
    )


class TestNextBatch:
    def test_an_empty_page_keeps_the_cursor(self):
        cursor = SpendCursor(timestamp=_T0, ids_at_timestamp=frozenset({"a"}))

        assert LLMGateway._next_batch([], cursor, _T0, complete=True) == ([], cursor, True)

    def test_a_cursor_at_the_last_timestamp_keeps_its_ids(self):
        cursor = SpendCursor(timestamp=_T0, ids_at_timestamp=frozenset({"a"}))

        rows, next_cursor, caught_up = LLMGateway._next_batch([_usage("a", _T0), _usage("b", _T0)], cursor, _T0, complete=False)

        assert [row.row_id for row in rows] == ["b"]
        assert next_cursor == SpendCursor(timestamp=_T0, ids_at_timestamp=frozenset({"a", "b"}))
        assert caught_up is False

    def test_a_row_past_until_means_caught_up(self):
        rows, _, caught_up = LLMGateway._next_batch([_usage("a", _T0), _usage("b", _T0 + timedelta(milliseconds=1))], None, _T0, complete=False)

        assert [row.row_id for row in rows] == ["a"]
        assert caught_up is True

    def test_a_full_page_with_nothing_new_raises_instead_of_stalling(self):
        cursor = SpendCursor(timestamp=_T0, ids_at_timestamp=frozenset({"a", "b"}))

        with pytest.raises(UsageTruncatedError):
            LLMGateway._next_batch([_usage("a", _T0), _usage("b", _T0)], cursor, _T0 + timedelta(seconds=5), complete=False)


class TestGatewayHTTP:
    @staticmethod
    def _http(handler) -> GatewayHTTP:
        return GatewayHTTP("fake", _BASE_URL, {"Authorization": "Bearer sk-secret"}, transport=httpx.MockTransport(handler))

    @pytest.mark.asyncio
    async def test_returns_the_json_body(self):
        http = self._http(lambda request: httpx.Response(200, json={"ok": True}))

        assert await http.request("GET", "/rows") == {"ok": True}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("response", "status", "auth"),
        [
            (httpx.Response(401), 401, True),
            (httpx.Response(403), 403, True),
            (httpx.Response(500), 500, False),
            (httpx.Response(404), 404, False),
            (httpx.Response(200, content=b"not json"), 200, False),
        ],
    )
    async def test_maps_failures_to_usage_retrieval_error(self, response, status, auth):
        http = self._http(lambda request: response)

        with pytest.raises(UsageRetrievalError) as caught:
            await http.request("GET", "/rows", params={"user": "someone"})

        assert (caught.value.gateway, caught.value.path, caught.value.status, caught.value.auth) == ("fake", "/rows", status, auth)
        assert "someone" not in str(caught.value)

    @pytest.mark.asyncio
    async def test_a_rejection_keeps_its_body_as_detail_only(self, caplog):
        caplog.set_level(logging.DEBUG)
        http = self._http(lambda request: httpx.Response(400, json={"error": "Budget with id 'ak-1' already exists."}))

        with pytest.raises(UsageRetrievalError) as caught:
            await http.request("POST", "/budget/new", json={})

        assert "already exists" in caught.value.detail
        assert "already exists" not in str(caught.value) and "already exists" not in caplog.text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ReadTimeout, httpx.DecodingError, httpx.TooManyRedirects])
    async def test_maps_transport_errors(self, error):
        def handler(request):
            raise error("down", request=request)

        with pytest.raises(UsageRetrievalError) as caught:
            await self._http(handler).request("GET", "/rows")

        assert caught.value.status is None and caught.value.auth is False

    @pytest.mark.asyncio
    async def test_logs_carry_the_path_never_the_query_or_key(self, caplog):
        caplog.set_level(logging.DEBUG)
        caplog.set_level(logging.DEBUG, logger="httpx")  # other tests may have raised it
        http = self._http(lambda request: httpx.Response(200, json={}))

        await http.request("GET", "/rows", params={"end_user": "secret-user"})

        assert "/rows" in caplog.text
        assert "HTTP Request" in caplog.text  # httpx's own line is there, redacted
        assert "secret-user" not in caplog.text
        assert "sk-secret" not in caplog.text

    @pytest.mark.asyncio
    async def test_a_mixed_case_base_url_is_still_redacted(self, caplog):
        caplog.set_level(logging.INFO, logger="httpx")
        http = GatewayHTTP("fake", "https://GW-Mixed.test/", transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))

        await http.request("GET", "/rows", params={"end_user": "secret-user"})

        assert "gw-mixed.test/rows" in caplog.text
        assert "secret-user" not in caplog.text

    @pytest.mark.asyncio
    async def test_other_hosts_keep_their_query_in_httpx_logs(self, caplog):
        caplog.set_level(logging.INFO, logger="httpx")
        self._http(lambda request: httpx.Response(200))  # registers the gateway's prefix
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))) as client:
            await client.get("https://other.test/x", params={"q": "kept"})

        assert "q=kept" in caplog.text

    def test_one_client_per_loop_and_a_per_call_client_elsewhere(self):
        http = self._http(lambda request: httpx.Response(200, json={}))
        bound = asyncio.new_event_loop()
        try:
            bound.run_until_complete(http.request("GET", "/a"))
            client = http._client
            bound.run_until_complete(http.request("GET", "/b"))
            assert http._client is client

            asyncio.run(http.request("GET", "/c"))  # another, live-elsewhere loop: a per-call client
            assert http._client is client

            asyncio.run(http.close())  # from another loop: dropped, not awaited on the wrong loop
            assert http._client is None
        finally:
            bound.close()

    def test_a_dead_bound_loop_is_replaced(self):
        http = self._http(lambda request: httpx.Response(200, json={}))
        asyncio.run(http.request("GET", "/a"))
        first = http._client

        asyncio.run(http.request("GET", "/b"))

        assert http._client is not first


class TestLLMGatewayFactory:
    def test_a_dotted_path_builds_the_class_with_config_and_secrets(self, monkeypatch):
        secrets = MagicMock(spec=SecretManager)
        monkeypatch.setattr(SecretManager, "current", classmethod(lambda cls: secrets))
        config = _config()

        gateway = LLMGatewayFactory.create(config)

        assert isinstance(gateway, _FakeGateway)
        assert gateway.config is config and gateway.secrets is secrets

    @pytest.mark.parametrize("type_", ["nosuchgateway", "openai"])
    def test_an_unknown_name_raises(self, type_):
        with pytest.raises(AKConfigError, match="unknown cost.gateway.type"):
            LLMGatewayFactory.create(_config(type_))

    def test_a_dotted_path_to_another_class_raises(self):
        with pytest.raises(AKConfigError, match="not a LLMGateway subclass"):
            LLMGatewayFactory.create(_config("datetime.datetime"))

    def test_gateway_names_are_exported(self):
        assert {"LLMGateway", "LLMGatewayFactory"} <= set(cost.__all__)
