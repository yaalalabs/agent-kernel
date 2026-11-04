import logging

from agentkernel.aws import ECSAgentRunner
from agentkernel.framework.adk import GoogleADKModule, GoogleADKToolBuilder
from google.adk.agents import Agent as GoogleAgent

logging.basicConfig(level=logging.INFO)


def get_weather(location: str) -> str:
    """Get the current weather in a given location."""
    return f"The weather in {location} is sunny and 75 degrees."


general_agent = GoogleAgent(
    name="general",
    model="gemini-3.1-flash-live-preview",
    description="Agent for general questions",
    instruction="You provide assistance with general queries. Give short and direct answers.",
    tools=GoogleADKToolBuilder.bind([get_weather]),
)

GoogleADKModule([general_agent])

if __name__ == "__main__":
    ECSAgentRunner.run()
