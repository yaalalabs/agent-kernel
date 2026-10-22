"""Claude Agent SDK agents served through the Agent Kernel REST API."""

from agentkernel.api import RESTAPI
from agentkernel.claude import ClaudeAgentSpec, ClaudeModule, ClaudeToolBuilder
from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions

MODEL = "sonnet"


def get_weather(city: str) -> str:
    """Returns the weather for a given city (example stub)."""
    if city == "Tokyo":
        return "The weather in Tokyo is sunny."
    else:
        return f"Cannot find weather for {city}."


def options(system_prompt: str, agents: dict[str, AgentDefinition] | None = None) -> ClaudeAgentOptions:
    """
    ClaudeAgentOptions locked down for a server: no built-in Claude Code tools (Bash, Read, Write, ...), no
    ~/.claude settings or CLAUDE.md, and no unapproved tool calls. Agent Kernel approves the tools bound with
    ClaudeToolBuilder. `strict_mcp_config` and `verbatim_prompts` additionally keep local MCP configuration and
    `@path` expansion out of API requests; `max_turns` bounds a runaway run.
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


math_agent = ClaudeAgentSpec(
    name="math",
    description="Specialist agent for math questions",
    options=options(
        "You provide help with math problems. Give short and direct answers exactly to the question. "
        "Don't provide any explanations nor additional details."
    ),
)

general_agent = ClaudeAgentSpec(
    name="general",
    description="Agent for general questions",
    options=options(
        "You provide assistance with general queries. Give short and direct answers exactly to the question. "
        "Don't provide any explanations nor additional details"
    ),
)

weather_agent = ClaudeAgentSpec(
    name="weather",
    description="Agent that provides weather information",
    options=options(
        "You provide weather information upon request. Use the get_weather tool for all weather-related questions."
    ),
    tools=ClaudeToolBuilder.bind([get_weather]),
)

# Native subagents share triage's session and refer to its bound tool by its MCP name.
triage_agent = ClaudeAgentSpec(
    name="triage",
    description="Front-line agent that routes each question to the right specialist",
    options=options(
        "You determine which agent to use based on the user's question. Give short and direct answers "
        "exactly to the question. Don't provide any explanations nor additional details",
        agents={
            "general": AgentDefinition(
                description=general_agent.description, prompt=general_agent.options.system_prompt
            ),
            "math": AgentDefinition(description=math_agent.description, prompt=math_agent.options.system_prompt),
            "weather": AgentDefinition(
                description=weather_agent.description,
                prompt=weather_agent.options.system_prompt,
                tools=[ClaudeToolBuilder.mcp_tool_name("get_weather")],
            ),
        },
    ),
    tools=weather_agent.tools,
)

ClaudeModule([triage_agent, math_agent, general_agent, weather_agent])

# Entry point referenced by the Dockerfile (from app import runner; runner()).
runner = RESTAPI.run

if __name__ == "__main__":
    runner()
