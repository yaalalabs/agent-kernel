"""AgentgatewayGateway (spec §5.2) over a request-log database built from agentgateway v1.7.0's own migrations
(tests/fixtures/agentgateway): the LLMGatewayContract on SQLite, the real row shape, sqlx's variable timestamp
fraction, filters, total_spend, the migration probe, read-only access and configuration errors.

The Postgres contract run needs a server: set AK_TEST_AGW_POSTGRES_URL (a database the test may drop tables in).
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agentkernel.core.config import _CostGatewayConfig
from agentkernel.core.util.factory import AKConfigError
from agentkernel.cost import Attribution, LLMGatewayFactory, ModelUsage, SpendTotal, UsageQuery, UsageRetrievalError, UsageWindow
from agentkernel.cost.gateway.agentgateway import AgentgatewayGateway, RequestLogDatabase
from agentkernel.cost.testing import LLMGatewayContract
from agentkernel.secret import SecretManager

_FIXTURES = Path(__file__).parent / "fixtures" / "agentgateway"
_MIGRATIONS_DDL = (
    "CREATE TABLE _agentgateway_request_log_migrations (version BIGINT PRIMARY KEY, description TEXT NOT NULL, "
    "installed_on TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, success BOOLEAN NOT NULL, checksum {blob} NOT NULL, "
    "execution_time BIGINT NOT NULL)"
)
_T0 = datetime(2026, 11, 17, 7, 54, 37, tzinfo=timezone.utc)
_PG_URL = os.environ.get("AK_TEST_AGW_POSTGRES_URL")


def _autosi(value: datetime) -> str:
    """started_at as sqlx stores it in SQLite: RFC 3339 with chrono's AutoSi fraction (none, 3 or 6 digits here)."""
    whole = value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    micro = value.microsecond
    fraction = "" if micro == 0 else f".{micro // 1000:03d}" if micro % 1000 == 0 else f".{micro:06d}"
    return f"{whole}{fraction}+00:00"


def _log_row(gateway: AgentgatewayGateway, usage: ModelUsage) -> dict:
    """A request_logs row as agentgateway 1.7 writes it for ``usage``: ids through the gateway's transform, and
    session and request id only in attributes_json, and only when set."""

    def encoded(value):
        return None if value is None else gateway.gateway_user_id(value)

    attributes = {
        "agentgateway.user": encoded(usage.user_id),
        "agentgateway.group": encoded(usage.agent_id),
        "agentgateway.session": encoded(usage.session_id),
        "ak.request_id": encoded(usage.request_id),
    }
    return {
        "id": usage.row_id,
        "started_at": usage.timestamp,
        "provider": usage.provider,
        "model": usage.model,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cached": usage.cached_input_tokens,
        "cost": None if usage.provider_cost is None else float(usage.provider_cost),
        "user": encoded(usage.user_id),
        "group": encoded(usage.agent_id),
        "attributes": {key: value for key, value in attributes.items() if value is not None},
    }


_INSERT = (
    "INSERT INTO request_logs (id, started_at, completed_at, duration_ms, http_status, gen_ai_provider_name, "
    "gen_ai_request_model, gen_ai_response_model, input_tokens, output_tokens, total_tokens, cost, agentgateway_user, "
    "agentgateway_group, has_payload, attributes_json, cache_read_input_tokens) VALUES "
    "({p}, {p}, {p}, 17, 200, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {false}, {p}, {p})"
)


def _insert_params(row: dict, started_at) -> tuple:
    total = None if row["input_tokens"] is None else row["input_tokens"] + (row["output_tokens"] or 0)
    return (
        row["id"],
        started_at,
        started_at,
        row["provider"],
        row["model"],
        row["model"],
        row["input_tokens"],
        row["output_tokens"],
        total,
        row["cost"],
        row["user"],
        row["group"],
        json.dumps(row["attributes"]),
        row["cached"],
    )


def _usage(row_id: str, at: datetime, **overrides) -> ModelUsage:
    values = {
        "user_id": "oidc|https%3A%2F%2Fissuer.example|user-123",
        "agent_id": None,
        "session_id": None,
        "request_id": None,
        "provider": "openai",
        "model": "gpt-4o-mini",
        "input_tokens": 12,
        "output_tokens": 3,
        "cached_input_tokens": None,
        "provider_cost": Decimal("0.0000036"),
        "billed_cost": None,
        "currency": "USD",
        "timestamp": at,
        "row_id": row_id,
    }
    return ModelUsage(**(values | overrides))


# SQLite


def _sqlite_db(path: Path, versions=(1, 2)) -> Path:
    with sqlite3.connect(path) as conn:
        for migration in sorted((_FIXTURES / "sqlite").glob("*.sql")):
            conn.executescript(migration.read_text())
        conn.execute(_MIGRATIONS_DDL.format(blob="BLOB"))
        conn.executemany(
            "INSERT INTO _agentgateway_request_log_migrations (version, description, success, checksum, execution_time) VALUES (?, 'm', 1, x'00', 1)",
            [(version,) for version in versions],
        )
    return path


def _sqlite_insert(path: Path, rows: list[dict]) -> None:
    with sqlite3.connect(path) as conn:
        conn.executemany(_INSERT.format(p="?", false="0"), [_insert_params(row, _autosi(row["started_at"])) for row in rows])


def _sqlite_gateway(path: Path) -> AgentgatewayGateway:
    config = _CostGatewayConfig(type="agentgateway", base_url="http://agw.test:4000", database={"url": str(path)})
    return AgentgatewayGateway(config, MagicMock())


@pytest.fixture
def db_path(tmp_path) -> Path:
    return _sqlite_db(tmp_path / "agw.db")


@pytest.fixture
def gateway(db_path) -> AgentgatewayGateway:
    gateway = _sqlite_gateway(db_path)
    gateway.db_path = db_path  # type: ignore[attr-defined]
    return gateway


def _seed(gateway: AgentgatewayGateway, *usages: ModelUsage) -> None:
    _sqlite_insert(gateway.db_path, [_log_row(gateway, usage) for usage in usages])  # type: ignore[attr-defined]


class TestAgentgatewaySQLiteContract(LLMGatewayContract):
    page_size = 1000

    @pytest.fixture
    def gateway(self, db_path) -> AgentgatewayGateway:
        gateway = _sqlite_gateway(db_path)
        gateway.db_path = db_path  # type: ignore[attr-defined]
        return gateway

    def seed(self, gateway, rows):
        _seed(gateway, *rows)

    def fail(self, gateway, mode):
        if mode == "unreachable":
            gateway.db_path.unlink()
        elif mode == "malformed":
            with sqlite3.connect(gateway.db_path) as conn:
                conn.execute("DROP TABLE request_log_payloads")
                conn.execute("DROP TABLE request_logs")
        else:
            pytest.skip(f"a SQLite request log has no {mode} failure")


class TestRowShape:
    @pytest.mark.asyncio
    async def test_the_observed_v1_7_0_row_maps_fully(self, gateway):
        user = "oidc|https%3A%2F%2Fissuer.example|user-123"
        observed = _usage(
            "01a1e880-2fa0-702f-b52c-d31dada8393f",
            _T0 + timedelta(microseconds=326796),
            user_id=user,
            agent_id="support-agent",
            session_id="sess-42",
            request_id="req-abc",
        )
        _seed(gateway, observed)

        (row,) = (await gateway.fetch_usage(UsageQuery(user_id=user, start=_T0, end=_T0 + timedelta(seconds=1)))).rows

        assert row == observed

    @pytest.mark.asyncio
    async def test_absent_attribution_reads_none(self, gateway):
        _seed(gateway, _usage("r1", _T0, user_id="u2"))

        (row,) = (await gateway.fetch_usage(UsageQuery(user_id="u2", start=_T0, end=_T0 + timedelta(seconds=1)))).rows

        assert (row.agent_id, row.session_id, row.request_id, row.cached_input_tokens) == (None, None, None, None)

    @pytest.mark.asyncio
    async def test_rows_without_a_provider_are_not_model_calls(self, gateway):
        _seed(gateway, _usage("llm", _T0), _usage("mcp", _T0, provider=None, model=None, input_tokens=None, output_tokens=None, provider_cost=None))

        result = await gateway.fetch_usage(UsageQuery(start=_T0, end=_T0 + timedelta(seconds=1)))

        assert [row.row_id for row in result.rows] == ["llm"]


class TestTimestampFraction:
    """sqlx stores 0, 3, 6 or 9 fraction digits, so string comparison is only exact against whole seconds."""

    @pytest.mark.asyncio
    async def test_sub_second_bounds_are_exact(self, gateway):
        _seed(
            gateway,
            _usage("whole", _T0),
            _usage("milli", _T0 + timedelta(milliseconds=500)),  # stored "…37.500+00:00"
            _usage("micro", _T0 + timedelta(microseconds=500_001)),
            _usage("next", _T0 + timedelta(seconds=1)),
        )
        query = UsageQuery(start=_T0 + timedelta(milliseconds=500), end=_T0 + timedelta(seconds=1))

        rows = (await gateway.fetch_usage(query)).rows
        total = await gateway.total_spend(_usage("x", _T0).user_id, UsageWindow(start=query.start, end=query.end))

        assert [row.row_id for row in rows] == ["milli", "micro"]
        assert total.by_model["openai/gpt-4o-mini"].requests == 2


class TestFilters:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ({"agent_id": "billing,refunds"}, ["agent"]),
            ({"session_id": "s\r\n1"}, ["session"]),
            ({"model": "gpt-4o"}, ["model"]),
            ({"provider": "anthropic"}, ["provider"]),
        ],
    )
    async def test_each_filter_narrows(self, gateway, query, expected):
        _seed(
            gateway,
            _usage("plain", _T0),
            _usage("agent", _T0, agent_id="billing,refunds"),
            _usage("session", _T0, session_id="s\r\n1"),
            _usage("model", _T0, model="gpt-4o"),
            _usage("provider", _T0, provider="anthropic"),
        )

        result = await gateway.fetch_usage(UsageQuery(start=_T0, end=_T0 + timedelta(seconds=1), **query))

        assert [row.row_id for row in result.rows] == expected


class TestTotalSpend:
    @pytest.mark.asyncio
    async def test_groups_by_provider_and_model(self, gateway):
        user = "alice"
        _seed(
            gateway,
            _usage("a", _T0, user_id=user, cached_input_tokens=4, provider_cost=Decimal("0.001")),
            _usage("b", _T0 + timedelta(seconds=1), user_id=user, provider_cost=Decimal("0.0025")),
            _usage("c", _T0 + timedelta(seconds=2), user_id=user, model="gpt-4o", provider_cost=None),
            _usage("other-user", _T0, user_id="bob"),
        )

        total = await gateway.total_spend(user, UsageWindow(start=_T0, end=_T0 + timedelta(hours=1)))

        mini, full = total.by_model["openai/gpt-4o-mini"], total.by_model["openai/gpt-4o"]
        assert (mini.requests, mini.cached_input_tokens, mini.provider_cost, mini.unpriced_requests) == (2, 4, Decimal("0.0035"), 0)
        assert (full.requests, full.provider_cost, full.unpriced_requests) == (1, Decimal(0), 1)


class TestProbe:
    @pytest.mark.asyncio
    async def test_accepts_the_1_7_schema(self, gateway):
        await gateway.probe()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("versions", [(1,), (1, 2, 3), (1, 2, 4)])
    async def test_refuses_another_schema(self, tmp_path, versions):
        gateway = _sqlite_gateway(_sqlite_db(tmp_path / "other.db", versions))

        with pytest.raises(AKConfigError, match=r"migration versions \[" + ", ".join(map(str, versions))):
            await gateway.probe()

    @pytest.mark.asyncio
    async def test_a_missing_database_is_an_availability_error(self, tmp_path):
        with pytest.raises(UsageRetrievalError):
            await _sqlite_gateway(tmp_path / "missing.db").probe()


class TestDatabaseAccess:
    @pytest.mark.asyncio
    async def test_the_connection_is_read_only(self, gateway):
        await gateway.probe()  # opens the connection

        with pytest.raises(UsageRetrievalError):
            await gateway._db.fetch("DELETE FROM request_logs", {})

    @pytest.mark.asyncio
    @pytest.mark.parametrize("prefix", ["sqlite://", "sqlite:"])
    async def test_sqlx_style_urls(self, db_path, prefix):
        await RequestLogDatabase(f"{prefix}{db_path}?mode=rwc").fetch("SELECT 1 AS one", {})

    @pytest.mark.asyncio
    async def test_no_url_is_a_config_error(self):
        secrets = MagicMock()
        secrets.get.return_value = None
        secrets.describe.return_value = "cost.gateway.database.url or the AGW_DB_URL environment variable"
        config = _CostGatewayConfig(type="agentgateway", base_url="http://agw.test", database={})

        with pytest.raises(AKConfigError, match="AGW_DB_URL"):
            await AgentgatewayGateway(config, secrets).probe()

    @pytest.mark.asyncio
    async def test_the_url_secret_is_used(self, db_path):
        secrets = MagicMock()
        secrets.get.side_effect = lambda key, default=None: str(db_path) if key == "AGW_DB_URL" else default
        config = _CostGatewayConfig(type="agentgateway", base_url="http://agw.test", database={})

        await AgentgatewayGateway(config, secrets).probe()

    @pytest.mark.asyncio
    async def test_postgres_without_the_extra_names_it(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "psycopg", None)

        with pytest.raises(ImportError, match="'cost-agentgateway' extra"):
            await RequestLogDatabase("postgresql://ak:secret@db.internal/agw").fetch("SELECT 1", {})


class TestHeadersAndFactory:
    def test_all_four_ids_are_encoded_and_none_omitted(self, gateway):
        headers = gateway.attribution_headers(Attribution(user_id="a,b", agent_id="support", session_id="s\r\n"))

        assert headers == {
            "x-ak-user-id": gateway.gateway_user_id("a,b"),
            "x-ak-agent-id": "support",
            "x-ak-session-id": gateway.gateway_user_id("s\r\n"),
        }

    def test_the_factory_builds_it(self, monkeypatch, db_path):
        monkeypatch.setattr(SecretManager, "current", classmethod(lambda cls: MagicMock()))

        gateway = LLMGatewayFactory.create(_CostGatewayConfig(type="agentgateway", base_url="http://agw.test", database={"url": str(db_path)}))

        assert isinstance(gateway, AgentgatewayGateway)

    def test_it_never_recognises_a_budget_refusal(self, gateway):
        assert gateway.is_budget_refusal(Exception("ExceededBudget: budget_exceeded")) is False


# Postgres (env-gated)


@pytest.mark.skipif(not _PG_URL, reason="set AK_TEST_AGW_POSTGRES_URL to run the Postgres contract")
class TestAgentgatewayPostgresContract(LLMGatewayContract):
    page_size = 1000

    @pytest.fixture
    def gateway(self) -> AgentgatewayGateway:
        import psycopg

        with psycopg.connect(_PG_URL, autocommit=True) as conn:
            conn.execute("DROP TABLE IF EXISTS request_log_payloads, request_logs, _agentgateway_request_log_migrations")
            for migration in sorted((_FIXTURES / "postgres").glob("*.sql")):
                conn.execute(migration.read_text())
            conn.execute(_MIGRATIONS_DDL.format(blob="BYTEA"))
            conn.execute(
                "INSERT INTO _agentgateway_request_log_migrations (version, description, success, checksum, execution_time) "
                "VALUES (1, 'm', true, '\\x00', 1), (2, 'm', true, '\\x00', 1), (3, 'm', true, '\\x00', 1)"
            )
        config = _CostGatewayConfig(type="agentgateway", base_url="http://agw.test", database={"url": _PG_URL})
        return AgentgatewayGateway(config, MagicMock())

    def seed(self, gateway, rows):
        import psycopg

        with psycopg.connect(_PG_URL, autocommit=True) as conn, conn.cursor() as cursor:
            cursor.executemany(_INSERT.format(p="%s", false="false"), [_insert_params(_log_row(gateway, row), row.timestamp) for row in rows])

    def fail(self, gateway, mode):
        if mode == "unreachable":
            gateway._db = RequestLogDatabase("postgresql://postgres:ak@127.0.0.1:1/postgres")
        elif mode == "malformed":
            import psycopg

            with psycopg.connect(_PG_URL, autocommit=True) as conn:
                conn.execute("DROP TABLE request_logs CASCADE")
        else:
            pytest.skip(f"a Postgres request log has no {mode} failure")

    @pytest.mark.asyncio
    async def test_the_probe_accepts_postgres_migration_3(self, gateway):
        await gateway.probe()

    @pytest.mark.asyncio
    async def test_the_connection_is_read_only(self, gateway):
        with pytest.raises(UsageRetrievalError):
            await gateway._database().fetch("DELETE FROM request_logs", {})

    @pytest.mark.asyncio
    async def test_total_spend_sums_exactly_in_sql(self, gateway):
        self.seed(
            gateway,
            [
                _usage("a", _T0, user_id="alice", provider_cost=Decimal("0.1")),
                _usage("b", _T0, user_id="alice", provider_cost=Decimal("0.2")),
                _usage("c", _T0, user_id="alice", provider_cost=None),
            ],
        )

        total = await gateway.total_spend("alice", UsageWindow(start=_T0, end=_T0 + timedelta(seconds=1)))
        rows = (await gateway.fetch_usage(UsageQuery(user_id="alice", start=_T0, end=_T0 + timedelta(seconds=1)))).rows

        assert total == SpendTotal.from_rows(rows, "USD")
        assert total.by_model["openai/gpt-4o-mini"].provider_cost == Decimal("0.3")  # not 0.30000000000000004
