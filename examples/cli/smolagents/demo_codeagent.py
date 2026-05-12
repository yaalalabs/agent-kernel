import logging

from agentkernel.cli import CLI
from agentkernel.core import ToolContext
from agentkernel.smolagents import SmolagentsModule, SmolagentsToolBuilder

from smolagents import CodeAgent, LiteLLMModel


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

code_agent = CodeAgent(
    tools=SmolagentsToolBuilder.bind([get_weather]),
    model=model,
    name="codeagent",
    description=(
        "General-purpose agent that can use tools and Python code execution to answer questions. "
        "Always produce executable Python code when reasoning is needed."
    ),
    use_structured_outputs_internally=True,
)

SmolagentsModule(agents=[code_agent])

if __name__ == "__main__":
    CLI.main()
