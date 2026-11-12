import logging

from agentkernel.framework.openai import OpenAIModule, OpenAIToolBuilder
from agentkernel.integration.adapter import EdgeLifecycleRESTRequestHandler
from agentkernel.integration.livekit import LiveKitLifecycleAdapter
from agentkernel.pipeline import IOHandler
from agents.realtime import RealtimeAgent

logging.basicConfig(level=logging.INFO)


def get_weather(location: str) -> str:
    """Get the current weather in a given location."""
    return f"The weather in {location} is sunny and 75 degrees."


general_agent = RealtimeAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and direct answers.",
    tools=OpenAIToolBuilder.bind([get_weather]),
)

OpenAIModule([general_agent]).run_options(
    general_agent, model_config={"initial_model_settings": {"model_name": "gpt-realtime", "voice": "alloy"}}
)


if __name__ == "__main__":
    IOHandler.run(handlers=[EdgeLifecycleRESTRequestHandler(LiveKitLifecycleAdapter())])
