import logging

from google.adk.agents import Agent as GoogleAgent

from agentkernel.framework.adk import ADKToolBuilder, GoogleADKModule
from agentkernel.integration.adapter import GatewayRunner
from agentkernel.integration.livekit import LiveKitEdgeGateway
from agentkernel.pipeline import IOHandler

logging.basicConfig(level=logging.INFO)
_log = logging.getLogger(__name__)


def get_weather(location: str) -> str:
    """Get the current weather in a given location."""
    return f"The weather in {location} is sunny and 75 degrees."


general_agent = GoogleAgent(
    name="general",
    model="gemini-live-2.5-flash-preview",
    description="Agent for general questions",
    instruction="You provide assistance with general queries. Give short and direct answers.",
    tools=ADKToolBuilder.bind([get_weather]),
)

GoogleADKModule([general_agent])

gateway = LiveKitEdgeGateway(session_id="room_01")


if __name__ == "__main__":
    IOHandler.run(gateways=[GatewayRunner(gateway)])
