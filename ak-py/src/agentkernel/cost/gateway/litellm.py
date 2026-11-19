"""``LiteLLMGateway``: the LiteLLM proxy as a cost gateway, in ``end_user`` or ``customer_management`` mode (spec §5.1)."""

import hashlib
import json
import logging
import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import httpx

from ...core.util.factory import AKConfigError
from ..errors import UnsupportedCapabilityError, UsageRetrievalError, UsageTruncatedError
from ..model import Attribution, BudgetLimit, BudgetPeriod, GatewayCapabilities, GatewayFilter, ModelUsage, SpendCursor, UsageQuery, UsageResult
from .base import LLMGateway
from .http import GatewayHTTP

if TYPE_CHECKING:
    from ...core.config import _CostGatewayConfig
    from ...secret import SecretManager

_END_USER_CAPABILITIES = GatewayCapabilities(
    usage_retrieval=True,
    cost_retrieval=True,
    user_aggregation=True,  # client-side
    agent_aggregation=True,  # client-side, from request_tags
    custom_metadata=True,
    native_user_budget=True,
    request_level_budget_check=True,
    streaming_usage=True,  # with always_include_stream_usage
    filters=frozenset({GatewayFilter.USER, GatewayFilter.TIME_RANGE, GatewayFilter.MODEL}),
    row_cap=10_000,  # /spend/logs/v2 total count cap
)

# No per-member spend rows in this mode. shortcut: native budget sync is deferred until LiteLLM 1.111's customer
# management API is stable and verifiable (spec deviation 25); until then this mode attributes calls only.
_CUSTOMER_MANAGEMENT_CAPABILITIES = GatewayCapabilities(
    custom_metadata=True,
    request_level_budget_check=True,
    streaming_usage=True,
)

_BUDGET_EXCEEDED = "budget_exceeded"
_SPEND_LOGS = "/spend/logs/v2"
_PAGE_SIZE = 1000  # the route's maximum
_ROW_CAP = 10_000  # SPEND_LOGS_PAGINATION_COUNT_CAP: a total this high may be clamped
_AGENT_TAG = "ak-agent:"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_DURATIONS = {BudgetPeriod.DAILY: "1d", BudgetPeriod.WEEKLY: "7d", BudgetPeriod.MONTHLY: "1mo"}
_MIN_CUSTOMER_MANAGEMENT_VERSION = (1, 111)


class LiteLLMGateway(LLMGateway):
    """The LiteLLM proxy. ``end_user`` bills the proxy's end user; ``customer_management`` (LiteLLM 1.111+) bills a
    member of a customer organization."""

    name = "litellm"
    _log = logging.getLogger("ak.cost.gateway.litellm")

    def __init__(self, config: "_CostGatewayConfig", secrets: "SecretManager", *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        """
        :param transport: An httpx transport for tests; None uses the network.
        """
        super().__init__(config, secrets)
        self._end_user = config.litellm.api == "end_user"
        self.capabilities = _END_USER_CAPABILITIES if self._end_user else _CUSTOMER_MANAGEMENT_CAPABILITIES
        self._http = GatewayHTTP(self.name, config.base_url, transport=transport)

    async def close(self) -> None:
        await self._http.close()

    def attribution_headers(self, attribution: Attribution) -> dict[str, str]:
        headers: dict[str, str] = {}
        if attribution.user_id is not None:
            if self._end_user:
                headers["x-litellm-customer-id"] = self.gateway_user_id(attribution.user_id)
            else:
                headers["x-litellm-customer-org-alias"] = self.config.litellm.customer_org_alias
                headers["x-litellm-customer-member-id"] = self.gateway_user_id(attribution.user_id)
        if attribution.agent_id is not None:
            # The proxy splits this header on ",", which gateway_user_id never leaves in a value.
            headers["x-litellm-tags"] = f"ak-agent:{self.gateway_user_id(attribution.agent_id)}"
        metadata = {
            "ak_session_id": attribution.session_id,
            "ak_request_id": attribution.request_id,
            "ak_agent_id": attribution.agent_id,
        }
        metadata = {key: value for key, value in metadata.items() if value is not None}
        if metadata:
            # ensure_ascii escapes CR, LF and non-ASCII, so the raw ids are header-safe and round-trip exactly.
            headers["x-litellm-spend-logs-metadata"] = json.dumps(metadata)
        return headers

    def is_budget_refusal(self, error: BaseException) -> bool:
        """The proxy's ``budget_exceeded`` error, read from the body or, without one, the message; never the status."""
        bodies = [body for body in (getattr(error, "body", None), self._response_json(error)) if isinstance(body, dict)]
        if not bodies:
            message = str(error)
            return "ExceededBudget:" in message and _BUDGET_EXCEEDED in message
        # The OpenAI SDK keeps the inner "error" object as its body; a raw response holds the whole envelope.
        for body in bodies:
            for candidate in (body, body.get("error")):
                if isinstance(candidate, dict) and _BUDGET_EXCEEDED in (candidate.get("type"), candidate.get("litellm_error_type")):
                    return True
        return False

    @staticmethod
    def _response_json(error: BaseException) -> Any:
        response = getattr(error, "response", None)
        if not isinstance(response, httpx.Response):
            return None
        try:
            return response.json()
        except (ValueError, httpx.ResponseNotRead):
            return None

    # Usage reads (end_user only)

    async def fetch_usage(self, query: UsageQuery) -> UsageResult:
        """Every row of ``/spend/logs/v2`` for the query, bounded exactly to ``[start, end)`` on the client."""
        self._require("usage_retrieval")
        self._require_filters(query)
        rows: list[ModelUsage] = []
        page = 1
        while True:
            body = await self._spend_logs(query.user_id, query.start, query.end, query.model, page)
            if body["total"] >= _ROW_CAP or body.get("total_is_capped"):
                raise UsageTruncatedError(f"usage from {query.start} to {query.end} exceeds LiteLLM's {_ROW_CAP}-row cap")
            rows += [row for row in map(self._row, body["data"]) if query.start <= row.timestamp < query.end]
            if page * _PAGE_SIZE >= body["total"]:
                return UsageResult(rows=rows)
            page += 1

    async def fetch_usage_since(self, user_id: str, cursor: SpendCursor | None, until: datetime) -> tuple[list[ModelUsage], SpendCursor | None, bool]:
        """One page from the cursor's second through ``until``'s, bounded exactly on the client."""
        self._require("usage_retrieval")
        body = await self._spend_logs(user_id, cursor.timestamp if cursor else _EPOCH, until, None, 1)
        page = [self._row(raw) for raw in body["data"]]
        return self._next_batch(page, cursor, until, complete=body["total"] <= _PAGE_SIZE)

    def _require(self, capability: str) -> None:
        if not getattr(self.capabilities, capability):
            raise UnsupportedCapabilityError(self.name, capability)

    # Startup probe

    async def probe(self) -> None:
        """``customer_management`` needs LiteLLM 1.111+: read the version from ``/health/readiness``."""
        if self._end_user:
            self._log.info("LiteLLM `timezone` cannot be verified; budgets assume UTC")
            return
        body = await self._http.request("GET", "/health/readiness", headers=self._bearer(self._admin_key()))
        version = body.get("litellm_version") if isinstance(body, dict) else None
        match = re.match(r"(\d+)\.(\d+)", version) if isinstance(version, str) else None
        if match is None or (int(match[1]), int(match[2])) < _MIN_CUSTOMER_MANAGEMENT_VERSION:
            raise AKConfigError(f"cost.gateway.litellm.api: customer_management needs LiteLLM 1.111 or later; the proxy reports {version!r}")

    # Native budgets (end_user)

    @staticmethod
    def budget_id(limit: BudgetLimit) -> str:
        """The gateway budget row for a limit: equal limits share one row, so ``10`` and ``10.00`` do too."""
        key = f"{format(limit.amount.normalize(), 'f')}|{limit.currency}|{limit.period.value}"
        return "ak-" + hashlib.sha256(key.encode()).hexdigest()[:16]

    async def sync_budget_definitions(self, limits: Iterable[BudgetLimit]) -> None:
        """Upsert one budget row per distinct limit: ``/budget/new``, then ``/budget/update`` if it exists."""
        self._require("native_user_budget")
        distinct = {self.budget_id(limit): limit for limit in limits}
        for budget_id, limit in distinct.items():
            if limit.currency not in self.capabilities.currencies:
                raise AKConfigError(f"LiteLLM budgets are in USD; a {limit.currency} budget cannot be enforced by the gateway")
            payload = {"budget_id": budget_id, "max_budget": float(limit.amount), "budget_duration": _DURATIONS[limit.period]}
            await self._upsert("/budget/new", "/budget/update", payload)

    async def sync_budgets(self, budgets: Mapping[str, BudgetLimit | None]) -> None:
        """Upsert each user's customer row, linked to its budget row; ``None`` links none (``ak-system``)."""
        self._require("native_user_budget")
        for user_id, limit in budgets.items():
            payload = {"user_id": self.gateway_user_id(user_id)}
            if limit is not None:
                payload["budget_id"] = self.budget_id(limit)
            await self._upsert("/customer/new", "/customer/update", payload)

    async def _upsert(self, new_path: str, update_path: str, payload: dict[str, Any]) -> None:
        """Create, or update when the proxy answers 400 "already exists". Another 4xx is a rejected shape."""
        try:
            await self._admin_post(new_path, payload)
            return
        except UsageRetrievalError as exc:
            if not (exc.status == 400 and "already exists" in (exc.detail or "").lower()):
                self._raise_if_rejected(exc)
                raise
        try:
            await self._admin_post(update_path, payload)
        except UsageRetrievalError as exc:
            self._raise_if_rejected(exc)
            raise

    async def _admin_post(self, path: str, payload: dict[str, Any]) -> None:
        key = self._admin_key()
        if not key:
            where = self.secrets.describe(self.config.admin_key_key, "cost.gateway.admin_key")
            raise AKConfigError(f"LiteLLM budget sync needs an admin key; set {where}")
        await self._http.request("POST", path, json=payload, headers=self._bearer(key))

    @staticmethod
    def _raise_if_rejected(error: UsageRetrievalError) -> None:
        """A non-auth 4xx means the proxy refused the request's shape: a configuration error, not an outage."""
        if error.status is not None and 400 <= error.status < 500 and not error.auth:
            raise AKConfigError(f"LiteLLM rejected POST {error.path} ({error.status}): {error.detail}") from error

    @staticmethod
    def _bearer(key: str | None) -> dict[str, str] | None:
        return {"Authorization": f"Bearer {key}"} if key else None

    async def _spend_logs(self, user_id: str | None, start: datetime, end: datetime, model: str | None, page: int) -> dict:
        params: dict[str, Any] = {
            "start_date": _second(start),
            "end_date": _second(end),
            "page": page,
            "page_size": _PAGE_SIZE,
            "sort_by": "startTime",
            "sort_order": "asc",
        }
        if user_id is not None:
            params["end_user"] = self.gateway_user_id(user_id)
        if model is not None:
            params["model"] = model
        body = await self._http.request("GET", _SPEND_LOGS, params=params, headers=self._bearer(self._admin_key()))
        if not (isinstance(body, dict) and isinstance(body.get("data"), list) and isinstance(body.get("total"), int)):
            raise UsageRetrievalError(f"gateway 'litellm' GET {_SPEND_LOGS} returned an unexpected body", gateway=self.name, path=_SPEND_LOGS)
        return body

    def _row(self, raw: dict) -> ModelUsage:
        """Map one spend-log row; a row that does not fit fails the whole read rather than being dropped."""
        try:
            metadata = _json_value(raw.get("metadata")) or {}
            logged = _json_value(metadata.get("spend_logs_metadata")) or {}
            usage = metadata.get("usage_object") or {}
            tags = _json_value(raw.get("request_tags")) or []
            agent = next((tag[len(_AGENT_TAG) :] for tag in tags if isinstance(tag, str) and tag.startswith(_AGENT_TAG)), None)
            timestamp = datetime.fromisoformat(raw["startTime"])
            return ModelUsage(
                user_id=self.raw_user_id(raw["end_user"]) if raw.get("end_user") else None,
                agent_id=self.raw_user_id(agent) if agent is not None else None,
                session_id=logged.get("ak_session_id"),
                request_id=logged.get("ak_request_id"),
                provider=raw.get("custom_llm_provider"),
                model=raw.get("model"),
                input_tokens=raw.get("prompt_tokens"),
                output_tokens=raw.get("completion_tokens"),
                cached_input_tokens=(usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
                provider_cost=raw.get("spend"),
                billed_cost=None,
                currency="USD",
                timestamp=timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc),
                row_id=raw["request_id"],
            )
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise UsageRetrievalError(
                f"gateway 'litellm' returned a spend-log row that does not map: {type(exc).__name__}", gateway=self.name, path=_SPEND_LOGS
            ) from None


def _second(value: datetime) -> str:
    """The route's date format; strftime drops the microseconds, flooring to the second."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _json_value(value: Any) -> Any:
    """A JSON column as a value: older proxies return metadata and tags as JSON strings."""
    return json.loads(value) if isinstance(value, str) else value
