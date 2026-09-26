import logging

from agents import Agent as OpenAIAgent

from agentkernel.core.config import AKConfig
from agentkernel.framework.openai import OpenAIModule, OpenAIRealtimeAdapter, OpenAIToolBuilder
from agentkernel.integration.adapter import GatewayRunner
from agentkernel.integration.livekit import LiveKitEdgeGateway
from agentkernel.pipeline import IOHandler

logging.basicConfig(level=logging.INFO)
_log = logging.getLogger(__name__)


def get_weather(location: str) -> str:
    """Get the current weather in a given location."""
    return f"The weather in {location} is sunny and 75 degrees."


general_agent = OpenAIAgent(
    name="general",
    model="gpt-realtime",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and direct answers.",
    tools=OpenAIToolBuilder.bind([get_weather]),
)

OpenAIModule([general_agent], realtime_runner_cls=OpenAIRealtimeAdapter)

gateway = LiveKitEdgeGateway(session_id="room_01")


if __name__ == "__main__":
    IOHandler.run(gateways=[GatewayRunner(gateway)])
