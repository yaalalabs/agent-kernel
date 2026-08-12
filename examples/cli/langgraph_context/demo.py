import logging
from typing import Annotated

from agentkernel.cli import CLI
from agentkernel.core import AgentReplyText, PostHook, PreHook, Session, ToolContext
from agentkernel.langgraph import LangGraphModule, LangGraphToolBuilder
from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import InjectedState, create_react_agent
from langgraph.prebuilt.chat_agent_executor import AgentState
from langgraph.types import Command

logger = logging.getLogger("ak.example.langgraph_context")

CART_PREFIX = "Current cart:"

model = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)

SYSTEM_PROMPT = (
    "You are a grocery shopping assistant. Call `add_to_cart` only when the user clearly asks to "
    "add items, and `view_cart` when they ask what is in the cart. After using a tool, reply with a "
    "short, friendly message stating what changed or what the cart currently contains."
)


class ShoppingState(AgentState):
    """ReAct agent state plus a declared `cart` channel, which is what lets it round-trip via framework_context."""

    cart: list[str]


@tool
def add_to_cart(
    items: list[str],
    state: Annotated[ShoppingState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Add one or more grocery items to the user's cart.

    A native LangGraph tool: `@tool` plus `InjectedState`, writing the `cart` state channel through a
    `Command`. This is the write path — the runner reads the declared channel back after the run and
    stores it on `framework_context`.
    """
    cart = list(state.get("cart") or [])
    cart.extend(items)
    logger.debug("cart is now %s", cart)
    return Command(
        update={
            "cart": cart,
            "messages": [
                ToolMessage(
                    f"Added {', '.join(items)}. Cart now contains: {', '.join(cart)}",
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


def view_cart() -> str:
    """Report what is currently in the user's cart.

    A plain, framework-agnostic function bound through `LangGraphToolBuilder`: it takes no LangGraph
    types and reads the cart from the session via `ToolContext`, so the same function would work
    unchanged on any other framework. It sees the context as of the start of this turn — write-back
    happens once the run completes, so items added by `add_to_cart` in the *same* turn are not
    visible here (the state channel, used by `add_to_cart`, is the within-turn view).
    """
    context = ToolContext.get()
    session = context.session if context is not None else None
    cart = (session.get_framework_context() or {}).get("cart", []) if session is not None else []
    return ", ".join(cart) if cart else "(empty)"


class SeedCartContextPreHook(PreHook):
    """Seed an empty framework_context on the first turn so the graph has a cart channel to fill."""

    async def on_run(self, session, agent, requests):
        session = Session.current()
        if session is not None and session.get_framework_context() is None:
            session.set_framework_context({"cart": []})
        return requests

    def name(self) -> str:
        return "seed_cart_context"


class AppendCartPostHook(PostHook):
    """Append the current cart to every reply, read from the session rather than the graph state."""

    async def on_run(self, session, requests, agent, agent_reply):
        session = Session.current()
        if session is None or not isinstance(agent_reply, AgentReplyText):
            return agent_reply
        context = session.get_framework_context() or {}
        cart = context.get("cart", [])
        summary = ", ".join(cart) if cart else "(empty)"
        agent_reply.response = f"{agent_reply.response}\n\n{CART_PREFIX} {summary}"
        return agent_reply

    def name(self) -> str:
        return "append_cart"


# `add_to_cart` is already a LangChain tool, so it is passed through as-is; `view_cart` is a plain
# function that LangGraphToolBuilder.bind() wraps into a StructuredTool (and which also appends any
# enabled system tools, such as multimodal attachment analysis).
shopping_graph = create_react_agent(
    model,
    tools=[add_to_cart, *LangGraphToolBuilder.bind([view_cart])],
    state_schema=ShoppingState,
    prompt=SYSTEM_PROMPT,
    name="shopping",
)

LangGraphModule([shopping_graph]).pre_hook(shopping_graph, [SeedCartContextPreHook()]).post_hook(
    shopping_graph, [AppendCartPostHook()]
)

if __name__ == "__main__":
    CLI.main()
