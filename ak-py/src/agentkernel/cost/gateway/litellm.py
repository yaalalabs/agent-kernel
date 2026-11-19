"""``LiteLLMGateway``: the LiteLLM proxy as a cost gateway, in ``end_user`` or ``customer_management`` mode (spec §5.1)."""

import json
from typing import TYPE_CHECKING, Any

import httpx

from ..model import Attribution, GatewayCapabilities, GatewayFilter
from .base import LLMGateway

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


class LiteLLMGateway(LLMGateway):
    """The LiteLLM proxy. ``end_user`` bills the proxy's end user; ``customer_management`` (LiteLLM 1.111+) bills a
    member of a customer organization."""

    name = "litellm"

    def __init__(self, config: "_CostGatewayConfig", secrets: "SecretManager") -> None:
        super().__init__(config, secrets)
        self._end_user = config.litellm.api == "end_user"
        self.capabilities = _END_USER_CAPABILITIES if self._end_user else _CUSTOMER_MANAGEMENT_CAPABILITIES

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
