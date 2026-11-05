"""A Claude Agent SDK agent token-streamed over SSE through the Agent Kernel REST API."""

from agentkernel.api import RESTAPI
from agentkernel.claude import ClaudeAgentSpec, ClaudeModule, ClaudeToolBuilder
from claude_agent_sdk import ClaudeAgentOptions


def get_weather(city: str) -> str:
    """Returns the weather for a given city (example stub)."""
    if city == "Tokyo":
        return "The weather in Tokyo is sunny."
    return f"Cannot find weather for {city}."


# Locked down for a server: no built-in Claude Code tools (Bash, Read, Write, ...), no ~/.claude settings or
# CLAUDE.md, and no unapproved tool calls. Agent Kernel approves the tools bound with ClaudeToolBuilder.
weather_agent = ClaudeAgentSpec(
    name="weather",
    description="Weather assistant whose replies and tool calls stream to the client as they happen",
    options=ClaudeAgentOptions(
        model="sonnet",
        system_prompt=(
            "You are a weather assistant. Use the get_weather tool for every weather question. "
            "For anything else, answer in two or three short sentences."
        ),
        tools=[],
        setting_sources=[],
        strict_mcp_config=True,
        permission_mode="dontAsk",
        verbatim_prompts=True,
        max_turns=8,
    ),
    tools=ClaudeToolBuilder.bind([get_weather]),
)

ClaudeModule([weather_agent])

# Entry point referenced by the Dockerfile (from app import runner; runner()).
runner = RESTAPI.run

if __name__ == "__main__":
    runner()
