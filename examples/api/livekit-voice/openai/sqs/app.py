"""Agent Kernel realtime voice over SQS: the two-process pipeline.

SQS is a broker transport, so the pipeline is split across two processes that share the queues:

    python app.py io        # LiveKit edge gateway + REST API (Request/Response Handler)
    python app.py runner    # Agent Runner + the per-session realtime sockets

Both read the same config.yaml. Start LocalStack (or real SQS) first. Run the ``runner`` role as a **single
replica**: its RealtimeConnectionPool is process-local, and one gateway instance must own a room.
"""

import logging
import sys

from agentkernel.framework.openai import (
    OpenAIModule,
    OpenAIRealtimeAdapter,
    OpenAIToolBuilder,
)
from agentkernel.integration.adapter import GatewayRunner
from agentkernel.integration.livekit import LiveKitEdgeGateway
from agentkernel.pipeline import AgentRunner, IOHandler
from agents import Agent as OpenAIAgent

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


def run_io() -> None:
    IOHandler.run(gateways=[GatewayRunner(gateway)])


ENTRYPOINTS = {"io": run_io, "runner": AgentRunner.run}


def main(argv: list[str]) -> int:
    role = argv[1] if len(argv) > 1 else ""
    if role not in ENTRYPOINTS:
        print(f"usage: python app.py [{' | '.join(ENTRYPOINTS)}]", file=sys.stderr)
        return 2
    ENTRYPOINTS[role]()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
