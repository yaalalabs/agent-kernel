from agentkernel.claude import ClaudeAgentSpec, ClaudeModule, ClaudeToolBuilder
from agentkernel.cli import CLI
from agentkernel.core import AgentReplyText, PostHook, PreHook, ToolContext
from claude_agent_sdk import ClaudeAgentOptions

CART_PREFIX = "Current cart:"


def add_to_cart(item: str) -> str:
    """Add a grocery item to the shopping cart."""
    context = ToolContext.get().framework_context
    assert context is not None  # SeedCartContextPreHook creates it before the tool runs.
    cart = context["cart"]
    cart.append(item)
    return f"Added '{item}'."


def view_cart() -> str:
    """Show the grocery items currently in the shopping cart."""
    context = ToolContext.get().framework_context
    assert context is not None
    cart = context["cart"]
    return "The cart contains: " + ", ".join(cart) if cart else "The cart is empty."


class SeedCartContextPreHook(PreHook):
    """Create a cart for this session before its first Claude run."""

    async def on_run(self, session, agent, requests):
        if session is None:
            return requests
        context = session.get_framework_context()
        if context is None:
            session.set_framework_context({"cart": []})
        elif "cart" not in context:
            context["cart"] = []  # keep what is already there, add what the tools need
        return requests

    def name(self) -> str:
        return "seed_cart_context"


class AppendCartPostHook(PostHook):
    """Show the cart saved by the runner after every reply."""

    async def on_run(self, session, requests, agent, agent_reply):
        if session is None or not isinstance(agent_reply, AgentReplyText):
            return agent_reply
        cart = (session.get_framework_context() or {}).get("cart", [])
        summary = ", ".join(cart) if cart else "(empty)"
        agent_reply.response = f"{agent_reply.response}\n\n{CART_PREFIX} {summary}"
        return agent_reply

    def name(self) -> str:
        return "append_cart"


shopping_agent = ClaudeAgentSpec(
    name="shopping",
    description="Grocery shopping assistant with a cart saved across turns",
    options=ClaudeAgentOptions(
        model="sonnet",
        system_prompt=(
            "You are a grocery shopping assistant. Use add_to_cart when the user asks to add an item. "
            "Use view_cart when the user asks what is in the cart. Keep replies short."
        ),
        tools=[],
        setting_sources=[],
        strict_mcp_config=True,
        permission_mode="dontAsk",
        verbatim_prompts=True,
        max_turns=8,
    ),
    tools=ClaudeToolBuilder.bind([add_to_cart, view_cart]),
)

ClaudeModule([shopping_agent]).pre_hook(shopping_agent, [SeedCartContextPreHook()]).post_hook(
    shopping_agent, [AppendCartPostHook()]
)

if __name__ == "__main__":
    CLI.main()
