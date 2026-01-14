from agents import Agent as OpenAIAgent

from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agentkernel.core.multimodal import get_image
from agentkernel.telegram import AgentTelegramRequestHandler
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

# Create your agent with the get_image tool
general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions=(
        "You provide assistance with general queries. "
        "Give short and clear answers suitable for Telegram messaging."
    ),
    tools=[get_image],
)

# Initialize module with agent
OpenAIModule([general_agent])


if __name__ == "__main__":
    handler = AgentTelegramRequestHandler()
    RESTAPI.run([handler])
