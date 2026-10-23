from agentkernel.aws import ServerlessAgentRunner
from agentkernel.openai import OpenAIModule
from agents import Agent, function_tool

ORDERS = {"A-1001": "Shipped, arriving Friday"}


# The OpenAI Agents SDK builds a tool from a function, so this is the one module-level function
@function_tool
def get_order_status(order_id: str) -> str:
    """Look up the delivery status of an order by its id, e.g. A-1001."""
    return ORDERS.get(order_id.strip().upper(), f"Order {order_id} not found")


support_agent = Agent(
    name="support",
    handoff_description="Order and delivery questions",
    instructions="You answer questions about orders and deliveries. Always look the order up with "
    "get_order_status and report exactly what it returns. If the order is not found, say so; never guess.",
    tools=[get_order_status],
    model="gpt-4.1-mini",
)

triage_agent = Agent(
    name="triage",
    instructions="You are the front desk of an online shop. Hand order and delivery questions to the support "
    "agent. Politely decline anything unrelated to the shop's orders.",
    handoffs=[support_agent],
    model="gpt-4.1-mini",
)

OpenAIModule([triage_agent, support_agent])

# Runs each queued request; the Langfuse runner traces it and flushes the spans before the Lambda freezes
handler = ServerlessAgentRunner.handle
