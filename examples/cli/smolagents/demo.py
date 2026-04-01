import logging

from agentkernel.cli import CLI
from agentkernel.core import ToolContext
from agentkernel.smolagents import SmolagentsModule, SmolagentsToolBuilder

try:
    from smolagents import CodeAgent, InferenceClientModel, ToolCallingAgent
except ImportError as e:
    print(f"Failed to import smolagents: {e}")
    exit(1)


def get_weather(city: str) -> str:
    """Returns the weather for a given city (example stub).

    Args:
        city: The string name of the city.
    """
    logger = logging.getLogger(__name__)
    if ToolContext.get() and ToolContext.get().session:
        logger.debug("Session ID: %s", ToolContext.get().session.id)

    if city == "Tokyo":
        return "The weather in Tokyo is sunny."
    else:
        return f"Cannot find weather for {city}."


model = InferenceClientModel(model_id="Qwen/Qwen2.5-Coder-32B-Instruct")

math_agent = CodeAgent(
    tools=[],
    model=model,
    name="math",
    description="Specialist agent for math questions. You provide help with math problems.",
)

general_agent = CodeAgent(
    tools=[],
    model=model,
    name="general",
    description="Agent for general questions. You provide assistance with general queries. Give short and direct answers exactly to the question.",
)

weather_agent = CodeAgent(
    tools=SmolagentsToolBuilder.bind([get_weather]),
    model=model,
    name="weather",
    description="You provide weather information upon request. Use the get_weather tool for all weather-related questions.",
)

triage_agent = CodeAgent(
    tools=[],
    model=model,
    name="triage",
    description="You determine which agent to use based on the user's question. Call the appropriate managed agent.",
    managed_agents=[math_agent, general_agent, weather_agent],
)

SmolagentsModule(agents=[triage_agent, math_agent, general_agent, weather_agent])

if __name__ == "__main__":
    CLI.main()
