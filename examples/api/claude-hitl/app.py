"""A Claude tool call that pauses until a person approves or denies it."""

import logging

from agentkernel.api import RESTAPI
from agentkernel.claude import ClaudeAgentSpec, ClaudeModule, ClaudeToolBuilder
from claude_agent_sdk import ClaudeAgentOptions

logger = logging.getLogger(__name__)


def issue_refund(order_id: str) -> str:
    """Record a demo refund for an order after a person approves the call."""
    # This example does not contact a payment service. The log makes execution visible.
    logger.warning("DEMO REFUND EXECUTED for %s", order_id)
    return f"Demo refund recorded for {order_id}. No money was moved."


support = ClaudeAgentSpec(
    name="support",
    description="Handles demo refund requests with human approval",
    options=ClaudeAgentOptions(
        model="sonnet",
        system_prompt=(
            "You handle demo refunds. When asked to refund an order, call issue_refund exactly once with the order ID. "
            "Make only one tool call in a turn. If the tool is denied, say the refund was not recorded. "
            "Do not claim a refund happened unless the tool confirms it."
        ),
        tools=[],
        setting_sources=[],
        strict_mcp_config=True,
        permission_mode="dontAsk",
        verbatim_prompts=True,
        max_turns=8,
    ),
    tools=ClaudeToolBuilder.bind([issue_refund], needs_approval=True),
)

ClaudeModule([support])

if __name__ == "__main__":

    RESTAPI.run(handlers=RESTAPI.get_default_handlers())
