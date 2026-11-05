import logging

from agentkernel.claude import ClaudeAgentSpec, ClaudeModule, ClaudeToolBuilder
from agentkernel.cli import CLI
from agentkernel.core import ToolContext
from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions

MODEL = "sonnet"


def get_weather(city: str) -> str:
    """Returns the weather for a given city (example stub)."""
    logger = logging.getLogger(__name__)
    logger.debug("Session ID: %s", ToolContext.get().session.id)

    if city == "Tokyo":
        return "The weather in Tokyo is sunny."
    else:
        return f"Cannot find weather for {city}."


def options(system_prompt: str, agents: dict[str, AgentDefinition] | None = None) -> ClaudeAgentOptions:
    """
    ClaudeAgentOptions locked down for a server: no built-in Claude Code tools (Bash, Read, Write, ...), no
    ~/.claude settings or CLAUDE.md, and no unapproved tool calls. Agent Kernel approves the tools bound with
    ClaudeToolBuilder. `strict_mcp_config` and `verbatim_prompts` additionally keep local MCP configuration and
    `@path` expansion out of user prompts; `max_turns` bounds a runaway run.
    """
    return ClaudeAgentOptions(
        model=MODEL,
        system_prompt=system_prompt,
        tools=[],
        setting_sources=[],
        strict_mcp_config=True,
        permission_mode="dontAsk",
        verbatim_prompts=True,
        max_turns=8,
        agents=agents,
    )


# Each specialist is declared once, as a native AgentDefinition, and only the triage agent is registered with Agent
# Kernel. A subagent lists its tools: one that does not inherits every tool of the session, get_weather included.
# get_weather is bound to the triage agent, which serves it from its own session, so the triage agent can call it too.
triage_agent = ClaudeAgentSpec(
    name="triage",
    description="Front-line agent that routes each question to the right specialist",
    options=options(
        "You determine which agent to use based on the user's question. Give short and direct answers "
        "exactly to the question. Don't provide any explanations nor additional details",
        agents={
            "math": AgentDefinition(
                description="Specialist agent for math questions",
                prompt=(
                    "You provide help with math problems. Give short and direct answers exactly to the question. "
                    "Don't provide any explanations nor additional details."
                ),
                tools=[],
            ),
            "general": AgentDefinition(
                description="Agent for general questions",
                prompt=(
                    "You provide assistance with general queries. Give short and direct answers exactly to the "
                    "question. Don't provide any explanations nor additional details"
                ),
                tools=[],
            ),
            "weather": AgentDefinition(
                description="Agent that provides weather information",
                prompt=(
                    "You provide weather information upon request. "
                    "Use the get_weather tool for all weather-related questions."
                ),
                tools=[ClaudeToolBuilder.mcp_tool_name("get_weather")],
            ),
        },
    ),
    tools=ClaudeToolBuilder.bind([get_weather]),
)

ClaudeModule([triage_agent])

if __name__ == "__main__":
    CLI.main()
