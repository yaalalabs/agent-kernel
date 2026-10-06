import logging

from agent_framework import Agent, FunctionInvocationContext
from agent_framework_openai import OpenAIChatClient
from agentkernel.cli import CLI
from agentkernel.core import AgentReplyText, PostHook, PreHook
from agentkernel.maf import MAFModule, MAFToolBuilder

logger = logging.getLogger("ak.example.maf_context")

CART_PREFIX = "Current cart:"
NOTE_PREFIX = "Delivery note:"


# Tool 1: add_to_cart using native MAF FunctionInvocationContext
def add_to_cart(ctx: FunctionInvocationContext, item: str) -> str:
    """Add a grocery item to the shopping cart carried in the per-run context.

    Args:
        item: The grocery item to add to the cart.
    """
    context = ctx.session.state.get("ak_context", {})
    cart = context.get("cart", [])
    cart.append(item)
    context["cart"] = cart
    logger.debug("cart is now %s", cart)
    return f"Added '{item}'. The cart now has {len(cart)} item(s)."


# Tool 2: view_cart
def view_cart(ctx: FunctionInvocationContext) -> str:
    """Return the current contents of the shopping cart from the per-run context."""
    context = ctx.session.state.get("ak_context", {})
    cart = context.get("cart", [])
    if not cart:
        return "The cart is empty."
    return "The cart contains: " + ", ".join(cart)


# Tool 3: set_delivery_note
def set_delivery_note(ctx: FunctionInvocationContext, note: str) -> str:
    """Attach a delivery note to the order, e.g. where to leave it.

    Args:
        note: The delivery instruction to remember for this order.
    """
    context = ctx.session.state.get("ak_context", {})
    context["delivery_note"] = note
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
    """Append the stored framework_context to every reply, showing that the state round-tripped."""

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


client = OpenAIChatClient(model="gpt-4o-mini")

shopping_agent = Agent(
    client,
    name="shopping",
    description="Grocery shopping assistant that keeps a cart across turns",
    instructions="""
    You are a grocery shopping assistant.
    Use the add_to_cart tool whenever the user wants to add an item.
    Use the view_cart tool whenever they ask what is in their cart.
    Use the set_delivery_note tool whenever they say where or how the order should be delivered.
    Keep answers short and state only what changed or what the cart currently contains.
    """,
    tools=MAFToolBuilder.bind([add_to_cart, view_cart, set_delivery_note]),
)

MAFModule([shopping_agent]).pre_hook(shopping_agent, [SeedCartContextPreHook()]).post_hook(
    shopping_agent, [AppendCartPostHook()]
)

if __name__ == "__main__":
    CLI.main()
