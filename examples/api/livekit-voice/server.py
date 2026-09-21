import logging

from agentkernel.core.config import AKConfig
from agentkernel.framework.openai import OpenAIModule
from agentkernel.livekit import LiveKitEdgeGateway
from agentkernel.pipeline import IOHandler
from agents import Agent as OpenAIAgent

logging.basicConfig(level=logging.INFO)
_log = logging.getLogger(__name__)

general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and direct answers.",
)

OpenAIModule([general_agent])

config = AKConfig.get()

gateway = LiveKitEdgeGateway(
    room_url=config.livekit.livekit_url,
    api_key=config.livekit.api_key,
    api_secret=config.livekit.api_secret,
    agent_name="general",
    session_id="room_01",
)


if __name__ == "__main__":
    IOHandler.run(gateways=[gateway])
