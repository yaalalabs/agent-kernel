import logging
from typing import Annotated, Sequence, TypedDict

from agentkernel.cli import CLI
from agentkernel.core import AgentReplyText, PostHook, PreHook
from agentkernel.langgraph import LangGraphModule
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph, add_messages
from pydantic import BaseModel, Field

logger = logging.getLogger("ak.example.langgraph_context")


CART_PREFIX = "Current cart:"

model = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)


class ShoppingState(TypedDict):
    """Graph state. `cart` is a declared channel, which is what lets it round-trip via framework_context."""

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
    """Read the cart carried in the graph state, apply the user's request, and write it back."""
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


class SeedCartContextPreHook(PreHook):
    """Seed an empty framework_context on the first turn so the graph has a cart channel to fill."""

    async def on_run(self, session, agent, requests):
        if session is not None and session.get_framework_context() is None:
            session.set_framework_context({"cart": []})
        return requests

    def name(self) -> str:
        return "seed_cart_context"


class AppendCartPostHook(PostHook):
    """Append the current cart to every reply, read from the session rather than the graph state."""

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


shopping_graph = _build_shopping_graph()

LangGraphModule([shopping_graph]).pre_hook(shopping_graph, [SeedCartContextPreHook()]).post_hook(
    shopping_graph, [AppendCartPostHook()]
)

if __name__ == "__main__":
    CLI.main()
