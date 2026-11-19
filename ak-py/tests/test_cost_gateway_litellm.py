"""LiteLLMGateway (spec §5.1): capabilities per mode, attribution headers, budget-refusal recognition, factory branch.

The LLMGatewayContract runs here once usage reads (2.3) and budget sync (2.4) exist.
"""

import json
import sys
from unittest.mock import MagicMock

import httpx
import openai
import pytest

from agentkernel.core.config import _CostGatewayConfig
from agentkernel.cost import Attribution, GatewayCapabilities, GatewayFilter, LLMGatewayFactory
from agentkernel.cost.gateway.litellm import LiteLLMGateway
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
            custom_metadata=True, native_user_budget=True, request_level_budget_check=True, streaming_usage=True
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
