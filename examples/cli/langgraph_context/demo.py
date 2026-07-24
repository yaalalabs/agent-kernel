import logging
from typing import Annotated, Sequence, TypedDict

from agentkernel.cli import CLI
from agentkernel.core import AgentReplyText, PostHook, PreHook, Session
from agentkernel.langgraph import LangGraphModule
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph, add_messages
from pydantic import BaseModel, Field

logger = logging.getLogger("ak.example.langgraph_context")

# The single reserved session key that carries a per-run, framework-agnostic context/state dict
# across turns. Reference the enum member rather than hardcoding the "framework_context" string.
FRAMEWORK_CONTEXT = Session.Keys.FRAMEWORK_CONTEXT.value

# Prefix the AppendCartPostHook adds to every reply so the current cart is always visible.
CART_PREFIX = "Current cart:"

model = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)


# --- The graph state: a cart channel is what makes the round-trip work -----------------------------
#
# Agent Kernel spreads the `framework_context` dict's top-level keys into the graph's input state, and
# reads back ONLY the keys the graph's state schema declares as channels. `cart` is declared here, so
# it round-trips; a key the schema does NOT declare would be silently dropped by LangGraph on the way
# out. (A prebuilt `create_react_agent` uses a fixed `AgentState` — messages/remaining_steps/
# structured_response — so seeding `cart` there would inject but never come back. See the README.)


class ShoppingState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    cart: list[str]


class CartUpdate(BaseModel):
    """Structured decision the shopping assistant makes for one turn."""

    items_to_add: list[str] = Field(
        default_factory=list,
        description="Grocery items the user asked to add this turn. Empty when they only ask what is in the cart.",
    )
    reply: str = Field(description="A short, friendly reply stating what changed or what the cart currently contains.")


SYSTEM_MESSAGE = SystemMessage(
    content="You are a grocery shopping assistant. Decide which items the user wants to add to their cart this turn "
    "and write a short reply. Add an item only when the user clearly asks to add it."
)

structured_model = model.with_structured_output(CartUpdate)


def shopping_node(state: ShoppingState) -> dict:
    """Read the cart carried in the graph state, apply the user's request, and write it back.

    The cart arrives in ``state["cart"]`` because Agent Kernel injected the session's
    ``framework_context`` into the graph input. Returning an updated ``cart`` puts the new value on
    the declared channel, which Agent Kernel then reads back and persists to the session.
    """
    cart = list(state.get("cart") or [])
    decision: CartUpdate = structured_model.invoke([SYSTEM_MESSAGE] + list(state["messages"]))
    cart.extend(decision.items_to_add)
    logger.debug("cart is now %s", cart)
    return {"messages": [AIMessage(content=decision.reply)], "cart": cart}


def _build_shopping_graph() -> "StateGraph":
    graph = StateGraph(ShoppingState)
    graph.add_node("shopping", shopping_node)
    graph.set_entry_point("shopping")
    graph.add_edge("shopping", END)
    return graph.compile(name="shopping")


# --- Hooks: seed the context on turn 1, and surface it on every reply ------------------------------


class SeedCartContextPreHook(PreHook):
    """Seed an empty framework_context on the first turn so the graph has a cart channel to fill.

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

    Post-hooks run after the runner has already written the produced state back to the session, so
    ``session.get(framework_context)`` here reflects this turn's changes. This makes the cart visible
    on every reply and shows that the same per-run state is reachable from a hook (via the session)
    as from inside the graph (via the state channel).
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


shopping_graph = _build_shopping_graph()

module = LangGraphModule([shopping_graph])
module.pre_hook(shopping_graph, [SeedCartContextPreHook()])
module.post_hook(shopping_graph, [AppendCartPostHook()])

if __name__ == "__main__":
    CLI.main()
