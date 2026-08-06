import logging

from agentkernel.cli import CLI
from agentkernel.core import AgentReplyText, PostHook, PreHook
from agentkernel.openai import OpenAIModule, OpenAIToolBuilder
from agents import Agent, RunContextWrapper, function_tool

logger = logging.getLogger("ak.example.openai_context")


CART_PREFIX = "Current cart:"


# The two tools are declared two different ways — the framework's own and Agent Kernel's — to show
# both work side by side, and both reach the per-run context.


# TOOL 1 — native: the SDK's ``@function_tool`` makes it a tool; it goes into ``tools=`` as is.
# A ``RunContextWrapper`` first parameter receives the run context, and framework_context is
# ``ctx.context`` — so mutating it in place updates the cart.
@function_tool
def add_to_cart(ctx: RunContextWrapper, item: str) -> str:
    """Add a grocery item to the shopping cart carried in the per-run context.

    Args:
        item: The grocery item to add to the cart.
    """
    context = ctx.context or {}
    cart = context.setdefault("cart", [])
    cart.append(item)
    logger.debug("cart is now %s", cart)
    return f"Added '{item}'. The cart now has {len(cart)} item(s)."


# TOOL 2 — Agent Kernel: the function stays plain and ``OpenAIToolBuilder.bind`` applies
# ``function_tool`` for you. Context is unchanged — a ``RunContextWrapper`` first parameter still
# receives framework_context.
def view_cart(ctx: RunContextWrapper) -> str:
    """Return the current contents of the shopping cart from the per-run context."""
    context = ctx.context or {}
    cart = context.get("cart", [])
    if not cart:
        return "The cart is empty."
    return "The cart contains: " + ", ".join(cart)


class SeedCartContextPreHook(PreHook):
    """Seed an empty framework_context on the first turn so the tools have a dict to populate."""

    async def on_run(self, session, agent, requests):
        if session is not None and session.get_framework_context() is None:
            session.set_framework_context({"cart": []})
        return requests

    def name(self) -> str:
        return "seed_cart_context"


class AppendCartPostHook(PostHook):
    """Append the current cart to every reply, read from the session rather than the run context."""

    async def on_run(self, session, requests, agent, agent_reply):
        if session is None or not isinstance(agent_reply, AgentReplyText):
            return agent_reply
        context = session.get_framework_context() or {}
        cart = context.get("cart", [])
        summary = ", ".join(cart) if cart else "(empty)"
        agent_reply.response = f"{agent_reply.response}\n\n{CART_PREFIX} {summary}"
        return agent_reply

    def name(self) -> str:
        return "append_cart"


shopping_agent = Agent(
    name="shopping",
    instructions="You are a grocery shopping assistant. Use the add_to_cart tool whenever the user wants to add an item, "
    "and the view_cart tool whenever they ask what is in their cart. Keep answers short and state only what changed "
    "or what the cart currently contains.",
    # Both styles in one list: the decorated tool as is, the plain one through the builder.
    tools=[add_to_cart] + OpenAIToolBuilder.bind([view_cart]),
)

OpenAIModule([shopping_agent]).pre_hook(shopping_agent, [SeedCartContextPreHook()]).post_hook(
    shopping_agent, [AppendCartPostHook()]
)

if __name__ == "__main__":
    CLI.main()
