"""``AgentgatewayGateway``: usage read straight from agentgateway's request-log database (spec §5.2).

agentgateway 1.7.x logs every request to SQLite or Postgres (``request_logs``). Agent Kernel opens that database
read-only: SQLite through the standard library, Postgres through psycopg (the ``cost-agentgateway`` extra).
"""

import asyncio
import logging
import re
import sqlite3
import threading
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from ...core.util.factory import AKConfigError, require_extra
from ..errors import UsageRetrievalError
from ..model import (
    Attribution,
    GatewayCapabilities,
    GatewayFilter,
    ModelSpend,
    ModelUsage,
    SpendCursor,
    SpendTotal,
    UsageQuery,
    UsageResult,
    UsageWindow,
)
from .base import LLMGateway

if TYPE_CHECKING:
    from ...core.config import _CostGatewayConfig
    from ...secret import SecretManager

_MIGRATIONS_TABLE = "_agentgateway_request_log_migrations"  # sqlx's table, renamed (agentgateway log_store.rs)
_REQUIRED_MIGRATIONS = frozenset({1, 2})  # 2 adds cache_read_input_tokens, which the reads select
_ALLOWED_MIGRATIONS = {"postgres": frozenset({1, 2, 3}), "sqlite": frozenset({1, 2})}  # agentgateway 1.7.x
_PAGE_SIZE = 1000
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MODEL = "COALESCE(gen_ai_response_model, gen_ai_request_model)"


class RequestLogDatabase:
    """Read-only queries against agentgateway's request log, on one lazily opened connection.

    SQLite queries run on a worker thread behind a ``threading.Lock``. A Postgres connection is bound to the event
    loop that opened it; a call from another loop (a sync bridge) uses its own short-lived connection. Errors become
    ``UsageRetrievalError``; the URL, which may carry credentials, never appears in one.
    """

    _log = logging.getLogger("ak.cost.gateway.agentgateway")

    def __init__(self, url: str) -> None:
        self.postgres = url.startswith(("postgres://", "postgresql://"))
        self._url = url
        self._sqlite: sqlite3.Connection | None = None
        self._sqlite_lock = threading.Lock()
        self._pg: Any = None  # psycopg.AsyncConnection; psycopg is optional
        self._pg_loop: asyncio.AbstractEventLoop | None = None
        self._pg_lock: asyncio.Lock | None = None

    @property
    def dialect(self) -> str:
        return "postgres" if self.postgres else "sqlite"

    def param(self, name: str) -> str:
        """A named placeholder in this dialect."""
        return f"%({name})s" if self.postgres else f":{name}"

    def attribute(self, key: str) -> str:
        """An ``attributes_json`` key as text, NULL when absent."""
        return f"attributes_json->>'{key}'" if self.postgres else f"json_extract(attributes_json, '$.\"{key}\"')"

    async def fetch(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if self.postgres:
            return await self._fetch_postgres(sql, params)
        return await asyncio.to_thread(self._fetch_sqlite, sql, params)

    async def close(self) -> None:
        with self._sqlite_lock:
            if self._sqlite is not None:
                self._sqlite.close()
                self._sqlite = None
        connection, self._pg = self._pg, None
        if connection is not None and self._pg_loop is asyncio.get_running_loop():
            await connection.close()

    def _fetch_sqlite(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        with self._sqlite_lock:
            try:
                if self._sqlite is None:
                    # sqlx-style URLs (sqlite:///path, sqlite:path?mode=rwc) are accepted as well as a bare path.
                    path = re.sub(r"^sqlite:(//)?", "", self._url).split("?", 1)[0]
                    self._sqlite = sqlite3.connect(f"file:{quote(path)}?mode=ro", uri=True, check_same_thread=False)
                    self._sqlite.row_factory = sqlite3.Row
                return [dict(row) for row in self._sqlite.execute(sql, params)]
            except sqlite3.Error as exc:
                if self._sqlite is not None:
                    self._sqlite.close()
                    self._sqlite = None  # reopened by the next call
                raise self._error(exc) from exc

    async def _fetch_postgres(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        with require_extra("cost-agentgateway", "cost.gateway.database.url: postgres"):
            import psycopg

        loop = asyncio.get_running_loop()
        if self._pg_loop is None or self._pg_loop.is_closed():
            self._pg, self._pg_loop, self._pg_lock = None, loop, asyncio.Lock()
        try:
            if self._pg_loop is not loop:
                async with await self._connect(psycopg) as connection:
                    return await self._query(connection, sql, params)
            assert self._pg_lock is not None
            async with self._pg_lock:
                if self._pg is None or self._pg.closed or self._pg.broken:
                    self._pg = await self._connect(psycopg)
                try:
                    return await self._query(self._pg, sql, params)
                except psycopg.Error:
                    if self._pg.broken:
                        self._pg = None  # reconnected by the next call
                    raise
        except psycopg.Error as exc:
            raise self._error(exc) from exc

    async def _connect(self, psycopg: Any) -> Any:
        from psycopg.rows import dict_row

        return await psycopg.AsyncConnection.connect(
            self._url, autocommit=True, row_factory=dict_row, connect_timeout=10, options="-c default_transaction_read_only=on"
        )

    @staticmethod
    async def _query(connection: Any, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        async with connection.cursor() as cursor:
            await cursor.execute(sql, params)
            return list(await cursor.fetchall())

    def _error(self, exc: Exception) -> UsageRetrievalError:
        self._log.warning(f"agentgateway request-log query failed: {type(exc).__name__}")
        return UsageRetrievalError(f"agentgateway request-log query failed: {type(exc).__name__}", gateway="agentgateway")


class AgentgatewayGateway(LLMGateway):
    """agentgateway 1.7.x. Attribution comes from ``x-ak-*`` headers its config maps to standard attributes."""

    name = "agentgateway"
    capabilities = GatewayCapabilities(
        usage_retrieval=True,
        cost_retrieval=True,
        user_aggregation=True,
        windowed_spend=True,
        agent_aggregation=True,
        session_filter=True,
        custom_metadata=True,
        streaming_usage=True,
        filters=frozenset(GatewayFilter),
    )

    def __init__(self, config: "_CostGatewayConfig", secrets: "SecretManager") -> None:
        super().__init__(config, secrets)
        self._db: RequestLogDatabase | None = None

    def attribution_headers(self, attribution: Attribution) -> dict[str, str]:
        ids = {
            "x-ak-user-id": attribution.user_id,
            "x-ak-agent-id": attribution.agent_id,
            "x-ak-session-id": attribution.session_id,
            "x-ak-request-id": attribution.request_id,
        }
        return {header: self.gateway_user_id(value) for header, value in ids.items() if value is not None}

    def is_budget_refusal(self, error: BaseException) -> bool:
        return False  # agentgateway enforces no per-user budget

    async def probe(self) -> None:
        """The request log must be at a schema version these queries were written against."""
        db = self._database()
        found = {int(row["version"]) for row in await db.fetch(f"SELECT version FROM {_MIGRATIONS_TABLE}", {})}
        allowed = _ALLOWED_MIGRATIONS[db.dialect]
        if not _REQUIRED_MIGRATIONS <= found <= allowed:
            raise AKConfigError(
                f"agentgateway's {db.dialect} request log is at migration versions {sorted(found)}; "
                f"Agent Kernel reads agentgateway 1.7.x ({sorted(allowed)})"
            )

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()

    async def fetch_usage(self, query: UsageQuery) -> UsageResult:
        self._require_filters(query)
        db = self._database()
        where, params = self._time_bounds(db, query.start, query.end, end_inclusive=False)
        filters = (
            ("agentgateway_user", "user", query.user_id and self.gateway_user_id(query.user_id)),
            ("agentgateway_group", "agent", query.agent_id and self.gateway_user_id(query.agent_id)),
            (db.attribute("agentgateway.session"), "session", query.session_id and self.gateway_user_id(query.session_id)),
            (_MODEL, "model", query.model),
            ("gen_ai_provider_name", "provider", query.provider),
        )
        for column, name, value in filters:
            if value is not None:
                where.append(f"{column} = {db.param(name)}")
                params[name] = value
        rows = self._rows(await db.fetch(self._select(db, where), params))
        return UsageResult(rows=[row for row in rows if query.start <= row.timestamp < query.end])

    async def total_spend(self, user_id: str, window: UsageWindow) -> SpendTotal:
        db = self._database()
        if not db.postgres:
            # SQLite stores costs as floats and timestamps with a variable fraction, so an exact total is summed here.
            result = await self.fetch_usage(UsageQuery(user_id=user_id, start=window.start, end=window.end))
            return SpendTotal.from_rows(result.rows, "USD")
        where, params = self._time_bounds(db, window.start, window.end, end_inclusive=False)
        where.append(f"agentgateway_user = {db.param('user')}")
        params["user"] = self.gateway_user_id(user_id)
        sql = (
            f"SELECT gen_ai_provider_name AS provider, {_MODEL} AS model, COUNT(*) AS requests, "
            "COALESCE(SUM(input_tokens), 0) AS input_tokens, COALESCE(SUM(output_tokens), 0) AS output_tokens, "
            "COALESCE(SUM(cache_read_input_tokens), 0) AS cached_input_tokens, "
            "COALESCE(SUM(cost::numeric), 0) AS cost, SUM(CASE WHEN cost IS NULL THEN 1 ELSE 0 END) AS unpriced "
            f"FROM request_logs WHERE gen_ai_provider_name IS NOT NULL AND {' AND '.join(where)} GROUP BY 1, 2"
        )
        total = SpendTotal(currency="USD", by_model={})
        for row in await db.fetch(sql, params):
            total.by_model[SpendTotal.key(row["provider"], row["model"])] = ModelSpend(
                model=row["model"],
                provider=row["provider"],
                requests=int(row["requests"]),
                input_tokens=int(row["input_tokens"]),
                output_tokens=int(row["output_tokens"]),
                cached_input_tokens=int(row["cached_input_tokens"]),
                provider_cost=Decimal(row["cost"]),
                unpriced_requests=int(row["unpriced"]),
            )
        return total

    async def fetch_usage_since(self, user_id: str, cursor: SpendCursor | None, until: datetime) -> tuple[list[ModelUsage], SpendCursor | None, bool]:
        db = self._database()
        where, params = self._time_bounds(db, cursor.timestamp if cursor else _EPOCH, until, end_inclusive=True)
        where.append(f"agentgateway_user = {db.param('user')}")
        params["user"] = self.gateway_user_id(user_id)
        page = self._rows(await db.fetch(f"{self._select(db, where)} LIMIT {_PAGE_SIZE}", params))
        return self._next_batch(page, cursor, until, complete=len(page) < _PAGE_SIZE)

    def _database(self) -> RequestLogDatabase:
        if self._db is None:
            database = self.config.database
            url = database and (database.url or self.secrets.get(database.url_key, default=None))
            if not url:
                key = database.url_key if database else "AGW_DB_URL"
                raise AKConfigError(
                    f"cost.gateway.type agentgateway reads its request-log database; set {self.secrets.describe(key, 'cost.gateway.database.url')}"
                )
            self._db = RequestLogDatabase(url)
        return self._db

    @staticmethod
    def _time_bounds(db: RequestLogDatabase, start: datetime, end: datetime, *, end_inclusive: bool) -> tuple[list[str], dict[str, Any]]:
        """``started_at`` bounds. Postgres compares exactly. SQLite stores text with a 0, 3, 6 or 9 digit fraction
        (sqlx's AutoSi), which only compares correctly against a whole second, so its bounds widen to whole seconds
        and the caller filters exactly."""
        if db.postgres:
            return [f"started_at >= {db.param('start')}", f"started_at {'<=' if end_inclusive else '<'} {db.param('end')}"], {
                "start": start,
                "end": end,
            }
        upper = _floor(end) + timedelta(seconds=1) if end_inclusive or end.microsecond else end
        return ["started_at >= :start", "started_at < :end"], {"start": _sqlite_text(_floor(start)), "end": _sqlite_text(upper)}

    @staticmethod
    def _select(db: RequestLogDatabase, where: Iterable[str]) -> str:
        cost = "cost::numeric" if db.postgres else "cost"
        return (
            f"SELECT id, started_at, gen_ai_provider_name AS provider, {_MODEL} AS model, input_tokens, output_tokens, "
            f"cache_read_input_tokens, {cost} AS cost, agentgateway_user, agentgateway_group, "
            f"{db.attribute('agentgateway.session')} AS session_id, {db.attribute('ak.request_id')} AS request_id "
            # Only model calls: agentgateway also logs MCP and plain HTTP traffic (its migration 2 uses this predicate).
            f"FROM request_logs WHERE gen_ai_provider_name IS NOT NULL AND {' AND '.join(where)} ORDER BY started_at, id"
        )

    def _rows(self, raw_rows: list[dict[str, Any]]) -> list[ModelUsage]:
        try:
            return [self._row(raw) for raw in raw_rows]
        except (KeyError, TypeError, ValueError) as exc:
            raise UsageRetrievalError(f"agentgateway returned a request-log row that does not map: {type(exc).__name__}", gateway=self.name) from None

    def _row(self, raw: dict[str, Any]) -> ModelUsage:
        started = raw["started_at"]
        timestamp = started if isinstance(started, datetime) else datetime.fromisoformat(started)
        ids = {key: raw[key] and self.raw_user_id(raw[key]) for key in ("agentgateway_user", "agentgateway_group", "session_id", "request_id")}
        return ModelUsage(
            user_id=ids["agentgateway_user"],
            agent_id=ids["agentgateway_group"],
            session_id=ids["session_id"],
            request_id=ids["request_id"],
            provider=raw["provider"],
            model=raw["model"],
            input_tokens=raw["input_tokens"],
            output_tokens=raw["output_tokens"],
            cached_input_tokens=raw["cache_read_input_tokens"],
            provider_cost=raw["cost"],
            billed_cost=None,
            currency="USD",
            timestamp=timestamp,
            row_id=raw["id"],
        )


def _floor(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(microsecond=0)


def _sqlite_text(value: datetime) -> str:
    """A whole second in the form sqlx stores, which compares correctly against any stored fraction."""
    return value.strftime("%Y-%m-%dT%H:%M:%S+00:00")
