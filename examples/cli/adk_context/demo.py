import logging

from agentkernel.adk import GoogleADKModule, GoogleADKToolBuilder
from agentkernel.cli import CLI
from agentkernel.core import AgentReplyText, PostHook, PreHook
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools import ToolContext

logger = logging.getLogger("ak.example.adk_context")


CART_PREFIX = "Current cart:"
NOTE_PREFIX = "Delivery note:"


def add_to_cart(item: str, tool_context: ToolContext) -> str:
    """Add a grocery item to the shopping cart carried in the per-run context.

    Args:
        item: The grocery item to add to the cart.
    """
    cart = list(tool_context.state.get("cart") or [])
    cart.append(item)
    # Assign back instead of mutating in place: ADK records a state delta on assignment.
    tool_context.state["cart"] = cart
    logger.debug("cart is now %s", cart)
    return f"Added '{item}'. The cart now has {len(cart)} item(s)."


def view_cart(tool_context: ToolContext) -> str:
    """Return the current contents of the shopping cart from the per-run context."""
    cart = tool_context.state.get("cart") or []
    if not cart:
        return "The cart is empty."
    return "The cart contains: " + ", ".join(cart)


def set_delivery_note(note: str, tool_context: ToolContext) -> str:
    """Attach a delivery note to the order, e.g. where to leave it.

    Args:
        note: The delivery instruction to remember for this order.
    """
    # `delivery_note` was never seeded into framework_context; ADK reads the whole state back, so it round-trips.
    tool_context.state["delivery_note"] = note
    logger.debug("delivery note is now %s", note)
    return f"Noted: {note}"


class SeedCartContextPreHook(PreHook):
    """Seed an empty framework_context on the first turn so the tools have state to populate."""

    async def on_run(self, session, agent, requests):
        if session is not None and session.get_framework_context() is None:
            session.set_framework_context({"cart": []})
        return requests

    def name(self) -> str:
        return "seed_cart_context"


class AppendCartPostHook(PostHook):
    """Append the stored framework_context to every reply, showing that the ADK state round-tripped."""

    async def on_run(self, session, requests, agent, agent_reply):
        if session is None or not isinstance(agent_reply, AgentReplyText):
            return agent_reply
        context = session.get_framework_context() or {}
        cart = context.get("cart") or []
        summary = ", ".join(cart) if cart else "(empty)"
        agent_reply.response = f"{agent_reply.response}\n\n{CART_PREFIX} {summary}"
        note = context.get("delivery_note")
        if note:
            agent_reply.response = f"{agent_reply.response}\n{NOTE_PREFIX} {note}"
        return agent_reply

    def name(self) -> str:
        return "append_cart"


shopping_agent = Agent(
    name="shopping",
    model=LiteLlm(model="openai/gpt-4o-mini"),
    description="Grocery shopping assistant that keeps a cart across turns",
    instruction="""
    You are a grocery shopping assistant.
    Use the add_to_cart tool whenever the user wants to add an item.
    Use the view_cart tool whenever they ask what is in their cart.
    Use the set_delivery_note tool whenever they say where or how the order should be delivered.
    Keep answers short and state only what changed or what the cart currently contains.
    """,
    tools=GoogleADKToolBuilder.bind([view_cart, set_delivery_note]) + [add_to_cart],
)

GoogleADKModule([shopping_agent]).pre_hook(shopping_agent, [SeedCartContextPreHook()]).post_hook(
    shopping_agent, [AppendCartPostHook()]
)

if __name__ == "__main__":
    CLI.main()
