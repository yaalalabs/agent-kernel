import logging

from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient
from agentkernel.cli import CLI
from agentkernel.core import ToolContext
from agentkernel.maf import MAFModule, MAFToolBuilder

logger = logging.getLogger(__name__)


def get_weather(location: str) -> str:
    """Get the current weather for a location."""
    logger.debug("Session ID: %s", ToolContext.get().session.id)
    return f"The weather in {location} is 72 degrees and sunny."


client = OpenAIChatClient(model="gpt-4o-mini")

maf_agent = Agent(
    client,
    instructions="You are a helpful assistant. Use the tools provided.",
    name="assistant",
    tools=MAFToolBuilder.bind([get_weather]),
)

MAFModule([maf_agent])

if __name__ == "__main__":
    CLI.main()
