import logging

from agentkernel.cli import CLI
from agentkernel.core import AgentReplyText, PostHook, PreHook, ToolContext
from agentkernel.pydanticai import PydanticAIModule, PydanticAIToolBuilder
from pydantic_ai import Agent, RunContext

logger = logging.getLogger("ak.example.pydanticai_context")

MODEL = "openai:gpt-4o-mini"

CART_PREFIX = "Current cart:"


# Native Pydantic AI tools: a first parameter typed RunContext receives the run's deps, which is where
# Agent Kernel injects framework_context. Mutations are made in place on ctx.deps.
def add_to_cart(ctx: RunContext[dict], item: str) -> str:
    """Add a grocery item to the shopping cart carried in the per-run context.

    Args:
        item: The grocery item to add to the cart.
    """
    cart = ctx.deps.setdefault("cart", [])
    cart.append(item)
    logger.debug("cart is now %s", cart)
    return f"Added '{item}'. The cart now has {len(cart)} item(s)."


def view_cart(ctx: RunContext[dict]) -> str:
    """Return the current contents of the shopping cart from the per-run context."""
    cart = ctx.deps.get("cart", [])
    if not cart:
        return "The cart is empty."
    return "The cart contains: " + ", ".join(cart)


# A framework-agnostic Agent Kernel tool for contrast: bound through PydanticAIToolBuilder, it takes no
# RunContext and reaches execution context through ToolContext instead, so it never sees deps.
def get_delivery_estimate(city: str) -> str:
    """Return the delivery estimate for a city.

    Args:
        city: The city to deliver to.
    """
    logger.debug("session id: %s", ToolContext.get().session.id)
    return f"Delivery to {city} takes 2 days."


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


# deps_type=dict documents that this agent's deps is the framework_context dict. Pydantic AI does not
# type-check deps at runtime, so this is a static-typing aid rather than a guard.
shopping_agent = Agent(
    model=MODEL,
    name="shopping",
    description="Grocery shopping assistant that keeps a cart across turns",
    instructions="You are a grocery shopping assistant. Use the add_to_cart tool whenever the user wants to add an item, "
    "the view_cart tool whenever they ask what is in their cart, and get_delivery_estimate for delivery questions. "
    "Keep answers short and state only what changed or what the cart currently contains.",
    deps_type=dict,
    tools=[add_to_cart, view_cart, *PydanticAIToolBuilder.bind([get_delivery_estimate])],
)

module = PydanticAIModule([shopping_agent])
module.pre_hook(shopping_agent, [SeedCartContextPreHook()])
module.post_hook(shopping_agent, [AppendCartPostHook()])

if __name__ == "__main__":
    CLI.main()
