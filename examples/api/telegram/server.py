import logging
import os

from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agentkernel.telegram import AgentTelegramRequestHandler
from agents import Agent as OpenAIAgent

# Configure logging
logging.basicConfig(level=logging.INFO)

# Create your agent (tools automatically attached by Framework if configured)
general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions=(
        "You provide assistance with general queries. "
        "Give short and clear answers suitable for Telegram messaging."
    ),
)

# Initialize module with agent
OpenAIModule([general_agent])


if __name__ == "__main__":
    handler = AgentTelegramRequestHandler()
    RESTAPI.run([handler])
