import logging

from agentkernel.cli import CLI
from agentkernel.core import ToolContext
from agentkernel.smolagents import SmolagentsModule, SmolagentsToolBuilder

from smolagents import CodeAgent, LiteLLMModel, ToolCallingAgent


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
    return f"Cannot find weather for {city}."


model = LiteLLMModel(model_id="openai/gpt-4o")

code_math_agent = CodeAgent(
    tools=[],
    model=model,
    name="code_math",
    description="Specialist agent for math and calculation questions.",
    use_structured_outputs_internally=True,
)

weather_agent = ToolCallingAgent(
    tools=SmolagentsToolBuilder.bind([get_weather]),
    model=model,
    name="weather",
    description="Specialist agent for weather questions. Always use the get_weather tool.",
)

router_agent = ToolCallingAgent(
    tools=[],
    model=model,
    name="router",
    description="Route each request to the most appropriate managed agent.",
    managed_agents=[code_math_agent, weather_agent],
)

SmolagentsModule(agents=[router_agent, code_math_agent, weather_agent])

if __name__ == "__main__":
    CLI.main()
