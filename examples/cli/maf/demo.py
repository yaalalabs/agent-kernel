import logging

from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient
from agentkernel.cli import CLI
from agentkernel.core import ToolContext
from agentkernel.maf import MAFModule, MAFToolBuilder

logger = logging.getLogger(__name__)


def get_weather(location: str) -> str:
    """Return a fixed example weather report for the requested location.

    :raises RuntimeError: If called without an active ToolContext.
    """
    logger.debug("Session ID: %s", ToolContext.get().session.id)
    return f"The weather in {location} is 72 degrees and sunny."


client = OpenAIChatClient(model="gpt-6-luna")

maf_agent = Agent(
    client,
    default_options={"reasoning": {"effort": "none"}},
    instructions="You are a helpful assistant. Use the tools provided.",
    name="assistant",
    tools=MAFToolBuilder.bind([get_weather]),
)

MAFModule([maf_agent])

if __name__ == "__main__":
    CLI.main()
