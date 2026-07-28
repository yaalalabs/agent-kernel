import logging

from agentkernel.cli import CLI
from agentkernel.core import ToolContext
from agentkernel.pydanticai import PydanticAIModule, PydanticAIToolBuilder
from pydantic_ai import Agent

MODEL = "openai:gpt-4o-mini"


def get_weather(city: str) -> str:
    """Returns the weather for a given city (example stub)."""
    logger = logging.getLogger(__name__)
    logger.debug("Session ID: %s", ToolContext.get().session.id)

    if city == "Tokyo":
        return "The weather in Tokyo is sunny."
    else:
        return f"Cannot find weather for {city}."


math_agent = Agent(
    model=MODEL,
    name="math",
    description="Specialist agent for math questions",
    instructions="You provide help with math problems. Give short and direct answers exactly to the question. "
    "Don't provide any explanations nor additional details.",
)

general_agent = Agent(
    model=MODEL,
    name="general",
    description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and direct answers exactly to the question. "
    "Don't provide any explanations nor additional details",
)

weather_agent = Agent(
    model=MODEL,
    name="weather",
    description="Agent that provides weather information",
    instructions="You provide weather information upon request. Use the get_weather tool for all weather-related questions.",
    tools=PydanticAIToolBuilder.bind([get_weather]),
)


# Pydantic AI has no built-in handoffs= primitive. Multi-agent routing is done with
# delegation-via-tool: the triage agent calls a specialist through a plain tool function that runs
# the sub-agent and returns its output.
async def ask_math(question: str) -> str:
    """Delegate a math question to the math specialist agent."""
    return str((await math_agent.run(question)).output)


async def ask_general(question: str) -> str:
    """Delegate a general-knowledge question to the general agent."""
    return str((await general_agent.run(question)).output)


async def ask_weather(question: str) -> str:
    """Delegate a weather question to the weather agent."""
    return str((await weather_agent.run(question)).output)


triage_agent = Agent(
    model=MODEL,
    name="triage",
    description="Front-line agent that routes each question to the right specialist",
    instructions="You determine which specialist should answer the user's question and call the matching tool: "
    "ask_math for math questions, ask_weather for weather questions, ask_general for everything else. "
    "Return the specialist's answer directly, with no extra explanation.",
    tools=PydanticAIToolBuilder.bind([ask_math, ask_general, ask_weather]),
)

PydanticAIModule([triage_agent, math_agent, general_agent, weather_agent])

if __name__ == "__main__":
    CLI.main()
