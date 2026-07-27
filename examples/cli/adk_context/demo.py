import logging

from agentkernel.adk import GoogleADKModule
from agentkernel.cli import CLI
from agentkernel.core import AgentReplyText, PostHook, PreHook, Session
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools import ToolContext

logger = logging.getLogger("ak.example.adk_context")

# The single reserved session key that carries a per-run, framework-agnostic context/state dict
# across turns. Reference the enum member rather than hardcoding the "framework_context" string.
FRAMEWORK_CONTEXT = Session.Keys.FRAMEWORK_CONTEXT.value

# Prefixes the AppendCartPostHook adds to every reply so the stored context is always visible.
CART_PREFIX = "Current cart:"
NOTE_PREFIX = "Delivery note:"


# --- Tools that read and write the per-run framework context --------------------------------------
#
# Agent Kernel merges `framework_context` into the ADK session state before the run and reads the
# accumulated state back afterwards, so a tool reads and writes it through ADK's own
# `tool_context.state`. ADK's state is in-memory only; the write-back into the session key is what
# makes it survive beyond this process.
#
# These tools are passed to the ADK agent DIRECTLY rather than through `GoogleADKToolBuilder.bind`.
# The builder consumes `tool_context` to set up Agent Kernel's own ToolContext and does not forward
# it, so a bound tool cannot reach ADK state. Rule of thumb: bind tools that need
# `ToolContext.get()` (session, runtime, agent); pass tools that need ADK state directly.


def add_to_cart(item: str, tool_context: ToolContext) -> str:
    """Add a grocery item to the shopping cart carried in the per-run context.

    Args:
        item: The grocery item to add to the cart.
    """
    cart = list(tool_context.state.get("cart") or [])
    cart.append(item)
    # Assign back instead of mutating in place — ADK records a state delta on assignment, and only
    # what lands in the state is read back and written to the session.
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
    # `delivery_note` was never seeded into framework_context — it is a brand-new key this tool adds
    # mid-run. On ADK the whole (stripped) state is read back, so it round-trips; on smolagents the
    # same write would be dropped, because there the read-back is restricted to pre-seeded keys.
    tool_context.state["delivery_note"] = note
    logger.debug("delivery note is now %s", note)
    return f"Noted: {note}"


class SeedCartContextPreHook(PreHook):
    """Seed an empty framework_context on the first turn so the tools have state to populate.

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
    """Append the stored context to every reply.

    This hook reads ``session.get(framework_context)`` — the Agent Kernel session, not ADK's state —
    and post-hooks run after the runner has already written the produced state back. So whatever it
    prints is proof that the ADK state round-tripped into the durable session key rather than merely
    living in ADK's in-memory session service.
    """

    async def on_run(self, session, requests, agent, agent_reply):
        if session is None or not isinstance(agent_reply, AgentReplyText):
            return agent_reply
        context = session.get(FRAMEWORK_CONTEXT) or {}
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
    tools=[add_to_cart, view_cart, set_delivery_note],
)

module = GoogleADKModule([shopping_agent])
module.pre_hook(shopping_agent, [SeedCartContextPreHook()])
module.post_hook(shopping_agent, [AppendCartPostHook()])

if __name__ == "__main__":
    CLI.main()
