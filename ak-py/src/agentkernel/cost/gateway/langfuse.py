"""``LangfuseGateway``: the Langfuse AI Gateway (beta), with usage read from v2 observations (spec §5.3).

The route and field names follow the vendor's generated API client (``langfuse.api.observations``) and the server's
query (``packages/shared/src/server/repositories/events.ts``): observations come newest first, time filters compare
at millisecond precision, and an empty page that carries a cursor is not the end.
"""

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx

from ...core.util.factory import AKConfigError
from ..errors import UsageRetrievalError
from ..model import (
    Attribution,
    GatewayCapabilities,
    GatewayFilter,
    ModelUsage,
    SpendCursor,
    SpendTotal,
    UsageQuery,
    UsageResult,
    UsageWindow,
)
from .base import LLMGateway
from .http import GatewayHTTP

if TYPE_CHECKING:
    from ...core.config import _CostGatewayConfig
    from ...secret import SecretManager

_OBSERVATIONS = "/api/public/v2/observations"
_FIELDS = "core,basic,usage,model,metadata,trace_context"
_PAGE_SIZE = 1000  # the route's maximum
# Langfuse ignores a value over 1 KiB, and every context header once they total over 8 KiB. Four values of at most
# 1 KiB each cannot reach 8 KiB, so only the per-value limit needs checking.
_VALUE_LIMIT = 1024
_AGENT_TAG = "ak-agent:"
# Where usageDetails keeps cache reads depends on the ingestion path. shortcut: unverified against a live gateway;
# the compatibility suite pins these keys, and a live check should replace the guess.
_CACHED_KEYS = ("input_cached_tokens", "cache_read_input_tokens", "input_cache_read")
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MILLISECOND = timedelta(milliseconds=1)


class LangfuseGateway(LLMGateway):
    """The Langfuse AI Gateway. ``api_key`` must be a service-account key, or Langfuse ignores ``langfuse-user-id``."""

    name = "langfuse"
    capabilities = GatewayCapabilities(
        usage_retrieval=True,
        cost_retrieval=True,
        user_aggregation=True,
        windowed_spend=True,
        agent_aggregation=True,
        session_filter=True,
        custom_metadata=True,
        streaming_usage=True,
        filters=frozenset({GatewayFilter.USER, GatewayFilter.SESSION, GatewayFilter.TIME_RANGE, GatewayFilter.MODEL}),
    )

    def __init__(self, config: "_CostGatewayConfig", secrets: "SecretManager", *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        """
        :param transport: An httpx transport for tests; None uses the network.
        """
        super().__init__(config, secrets)
        self._http = GatewayHTTP(self.name, config.base_url, transport=transport)

    async def close(self) -> None:
        await self._http.close()

    def attribution_headers(self, attribution: Attribution) -> dict[str, str]:
        """The ``langfuse-*`` context headers.

        :raises ValueError: If a value exceeds 1 KiB, which Langfuse would silently drop.
        """
        ids = {key: self.gateway_user_id(value) for key, value in attribution.model_dump().items() if value is not None}
        headers: dict[str, str] = {}
        if "user_id" in ids:
            headers["langfuse-user-id"] = ids["user_id"]
        if "session_id" in ids:
            headers["langfuse-session-id"] = ids["session_id"]
        if "agent_id" in ids:
            headers["langfuse-tags"] = f"{_AGENT_TAG}{ids['agent_id']}"
        # Comma-separated key:value pairs: a value must hold neither "," (gateway_user_id encodes it) nor ":". A colon
        # (Slack and Telegram request ids carry one) is encoded the same reversible way, so rows map back exactly.
        metadata = [f"{key}:{self._metadata_value(ids[key])}" for key in ("request_id", "agent_id") if key in ids]
        if metadata:
            headers["langfuse-metadata"] = ",".join(metadata)
        over = [name for name, value in headers.items() if len(value.encode()) > _VALUE_LIMIT]
        if over:
            raise ValueError(f"langfuse header limits exceeded: {over} (1 KiB per value)")
        return headers

    @staticmethod
    def _metadata_value(encoded: str) -> str:
        """A ``gateway_user_id`` value made colon-free, still reversed by ``raw_user_id``.

        A colon survives ``gateway_user_id`` only when it returned the id unchanged (its encoded form quotes ``:``), so
        quoting the value here is quoting the raw id under the same ``ak~`` prefix.
        """
        return encoded if ":" not in encoded else "ak~" + quote(encoded, safe="")

    def is_budget_refusal(self, error: BaseException) -> bool:
        return False  # Langfuse enforces no budgets

    def model_base_url(self, model: str) -> str:
        """Langfuse serves each provider's native API and does not translate between them."""
        base = self.config.base_url.rstrip("/")
        return f"{base}/anthropic/v1" if model.split("/", 1)[0] == "anthropic" else f"{base}/openai/v1"

    async def fetch_usage(self, query: UsageQuery) -> UsageResult:
        self._require_filters(query)
        rows = await self._observations(query.start, query.end, query.user_id, query.session_id, query.model)
        return UsageResult(rows=[row for row in rows if query.start <= row.timestamp < query.end])

    async def total_spend(self, user_id: str, window: UsageWindow) -> SpendTotal:
        # The metrics API has no cached-input measure, so the exact total is summed from the observations.
        result = await self.fetch_usage(UsageQuery(user_id=user_id, start=window.start, end=window.end))
        return SpendTotal.from_rows(result.rows, "USD")

    async def fetch_usage_since(self, user_id: str, cursor: SpendCursor | None, until: datetime) -> tuple[list[ModelUsage], SpendCursor | None, bool]:
        # Observations come newest first, so the whole range is read and the oldest page cut from it. The gateway
        # declares windowed_spend, so the spend ledger never calls this.
        rows = await self._observations(cursor.timestamp if cursor else _EPOCH, until + _MILLISECOND, user_id, None, None)
        remaining = self._next_batch(rows, cursor, until, complete=True)[0]
        return self._next_batch(remaining[:_PAGE_SIZE], cursor, until, complete=len(remaining) <= _PAGE_SIZE)

    async def _observations(self, start: datetime, end: datetime, user_id: str | None, session_id: str | None, model: str | None) -> list[ModelUsage]:
        """Every generation with ``start ≤ startTime < end`` widened to whole milliseconds, oldest first."""
        conditions: list[dict[str, Any]] = [
            {"type": "string", "column": "type", "operator": "=", "value": "GENERATION"},
            {"type": "datetime", "column": "startTime", "operator": ">=", "value": self._millis(start)},
            {"type": "datetime", "column": "startTime", "operator": "<", "value": self._millis(self._ceil_ms(end))},
        ]
        for column, value in (
            ("userId", user_id and self.gateway_user_id(user_id)),
            ("sessionId", session_id and self.gateway_user_id(session_id)),
            ("providedModelName", model),
        ):
            if value is not None:
                conditions.append({"type": "string", "column": column, "operator": "=", "value": value})
        params: dict[str, Any] = {"fields": _FIELDS, "limit": _PAGE_SIZE, "filter": json.dumps(conditions)}
        rows: list[ModelUsage] = []
        while True:
            body = await self._http.request("GET", _OBSERVATIONS, params=params, headers=self._auth())
            if not (isinstance(body, dict) and isinstance(body.get("data"), list) and isinstance(body.get("meta"), dict)):
                raise UsageRetrievalError(
                    f"gateway 'langfuse' GET {_OBSERVATIONS} returned an unexpected body", gateway=self.name, path=_OBSERVATIONS
                )
            rows += [self._row(raw) for raw in body["data"]]
            next_cursor = body["meta"].get("cursor")
            if not next_cursor:  # an empty page that still carries a cursor is not the end
                return sorted(rows, key=lambda row: (row.timestamp, row.row_id))
            params = {**params, "cursor": next_cursor}

    def _auth(self) -> dict[str, str]:
        key = self._admin_key()
        if not key or ":" not in key:
            where = self.secrets.describe(self.config.admin_key_key, "cost.gateway.admin_key")
            raise AKConfigError(f"Langfuse usage reads need admin_key as <public_key>:<secret_key>; set {where}")
        return {"Authorization": "Basic " + base64.b64encode(key.encode()).decode()}

    def _row(self, raw: dict[str, Any]) -> ModelUsage:
        try:
            usage = raw.get("usageDetails") or {}
            tags = raw.get("tags") or []
            metadata = raw.get("metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            agent = next((tag[len(_AGENT_TAG) :] for tag in tags if isinstance(tag, str) and tag.startswith(_AGENT_TAG)), None)
            request_id = metadata.get("request_id")
            timestamp = datetime.fromisoformat(raw["startTime"])
            return ModelUsage(
                user_id=raw.get("userId") and self.raw_user_id(raw["userId"]),
                agent_id=agent and self.raw_user_id(agent),
                session_id=raw.get("sessionId") and self.raw_user_id(raw["sessionId"]),
                request_id=request_id and self.raw_user_id(request_id),
                provider=None,  # observations carry no provider; static pricing matches the bare model name
                model=raw.get("providedModelName"),
                input_tokens=usage.get("input"),
                output_tokens=usage.get("output"),
                cached_input_tokens=next((usage[key] for key in _CACHED_KEYS if key in usage), None),
                provider_cost=raw.get("totalCost"),
                billed_cost=None,
                currency="USD",
                timestamp=timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc),
                row_id=raw["id"],
            )
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise UsageRetrievalError(
                f"gateway 'langfuse' returned an observation that does not map: {type(exc).__name__}", gateway=self.name, path=_OBSERVATIONS
            ) from None

    @staticmethod
    def _ceil_ms(value: datetime) -> datetime:
        """The next whole millisecond at or after ``value``: the server compares JS Dates, which hold milliseconds."""
        floored = value.replace(microsecond=value.microsecond // 1000 * 1000)
        return floored if floored == value else floored + _MILLISECOND

    @staticmethod
    def _millis(value: datetime) -> str:
        """ISO 8601 in UTC, floored to the millisecond."""
        return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
