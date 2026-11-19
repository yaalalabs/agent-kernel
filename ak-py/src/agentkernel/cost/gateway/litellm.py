"""``LiteLLMGateway``: the LiteLLM proxy as a cost gateway, in ``end_user`` or ``customer_management`` mode (spec §5.1)."""

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import httpx

from ..errors import UnsupportedCapabilityError, UsageRetrievalError, UsageTruncatedError
from ..model import Attribution, GatewayCapabilities, GatewayFilter, ModelUsage, SpendCursor, UsageQuery, UsageResult
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

# No per-member spend rows in this mode, so only native budgets work.
_CUSTOMER_MANAGEMENT_CAPABILITIES = GatewayCapabilities(
    custom_metadata=True,
    native_user_budget=True,
    request_level_budget_check=True,
    streaming_usage=True,
)

_BUDGET_EXCEEDED = "budget_exceeded"
_SPEND_LOGS = "/spend/logs/v2"
_PAGE_SIZE = 1000  # the route's maximum
_ROW_CAP = 10_000  # SPEND_LOGS_PAGINATION_COUNT_CAP: a total this high may be clamped
_AGENT_TAG = "ak-agent:"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class LiteLLMGateway(LLMGateway):
    """The LiteLLM proxy. ``end_user`` bills the proxy's end user; ``customer_management`` (LiteLLM 1.111+) bills a
    member of a customer organization."""

    name = "litellm"

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
        self._require_usage_retrieval()
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
        self._require_usage_retrieval()
        body = await self._spend_logs(user_id, cursor.timestamp if cursor else _EPOCH, until, None, 1)
        page = [self._row(raw) for raw in body["data"]]
        return self._next_batch(page, cursor, until, complete=body["total"] <= _PAGE_SIZE)

    def _require_usage_retrieval(self) -> None:
        if not self.capabilities.usage_retrieval:
            raise UnsupportedCapabilityError(self.name, "usage_retrieval")

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
        key = self._admin_key()
        headers = {"Authorization": f"Bearer {key}"} if key else None
        body = await self._http.request("GET", _SPEND_LOGS, params=params, headers=headers)
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
