import logging

from agentkernel.cli import CLI
from agentkernel.core import AgentReplyText, PostHook, PreHook, Session
from agentkernel.openai import OpenAIModule, OpenAIToolBuilder
from agents import Agent, RunContextWrapper

logger = logging.getLogger("ak.example.openai_context")

# The single reserved session key that carries a per-run, framework-agnostic context/state dict
# across turns. Reference the enum member rather than hardcoding the "framework_context" string.
FRAMEWORK_CONTEXT = Session.Keys.FRAMEWORK_CONTEXT.value

# Prefix the AppendCartPostHook adds to every reply so the current cart is always visible.
CART_PREFIX = "Current cart:"


# --- Tools that read and write the per-run framework context --------------------------------------
#
# The OpenAI Agents SDK injects Agent Kernel's `framework_context` dict as the run *context*. A tool
# receives it as `RunContextWrapper.context` and mutates it IN PLACE; Agent Kernel writes the mutated
# object back to the session after a successful run, so the cart survives to the next turn. This
# "full round-trip" (every key, including ones a tool adds mid-run) is specific to OpenAI — see the
# README for how other frameworks differ.


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


def view_cart(ctx: RunContextWrapper) -> str:
    """Return the current contents of the shopping cart from the per-run context."""
    context = ctx.context or {}
    cart = context.get("cart", [])
    if not cart:
        return "The cart is empty."
    return "The cart contains: " + ", ".join(cart)


class SeedCartContextPreHook(PreHook):
    """Seed an empty framework_context on the first turn so the tools have a dict to populate.

    An absent key means "no context / no injection" (existing apps are unaffected); a caller-set
    dict — even an empty one — is injected and round-tripped. Seeding ``{"cart": []}`` once, before
    the first run, is the recommended way to opt a session into carrying per-run state. On later
    turns the key is already present (persisted across turns) and is left untouched.
    """

    async def on_run(self, session, agent, requests):
        if session is not None and session.get(FRAMEWORK_CONTEXT) is None:
            session.set(FRAMEWORK_CONTEXT, {"cart": []})
        return requests

    def name(self) -> str:
        return "seed_cart_context"


class AppendCartPostHook(PostHook):
    """Append the current cart to every reply.

    Post-hooks run after the runner has already written the (mutated) context back to the session,
    so ``session.get(framework_context)`` here reflects this turn's changes. This makes the cart
    visible on every reply without the agent having to call view_cart, and shows that the same
    per-run state is reachable from a hook (via the session) as from a tool (via the run context).
    """

    async def on_run(self, session, requests, agent, agent_reply):
        if session is None or not isinstance(agent_reply, AgentReplyText):
            return agent_reply
        context = session.get(FRAMEWORK_CONTEXT) or {}
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
    tools=OpenAIToolBuilder.bind([add_to_cart, view_cart]),
)

module = OpenAIModule([shopping_agent])
module.pre_hook(shopping_agent, [SeedCartContextPreHook()])
module.post_hook(shopping_agent, [AppendCartPostHook()])

if __name__ == "__main__":
    CLI.main()
