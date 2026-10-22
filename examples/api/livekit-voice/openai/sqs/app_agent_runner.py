import logging

from agentkernel.aws import ECSAgentRunner
from agentkernel.openai import (
    OpenAIModule,
    OpenAIToolBuilder,
)
from agents.realtime import RealtimeAgent as OpenAIAgent

logging.basicConfig(level=logging.INFO)


def get_weather(location: str) -> str:
    """Get the current weather in a given location."""
    return f"The weather in {location} is sunny and 75 degrees."


general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and direct answers.",
    tools=OpenAIToolBuilder.bind([get_weather]),
)

OpenAIModule([general_agent]).run_options(general_agent, config={"model_settings": {"model_name": "gpt-realtime"}})

if __name__ == "__main__":
    ECSAgentRunner.run()
