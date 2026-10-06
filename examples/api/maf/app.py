from agent_framework import Agent
from agent_framework_openai import OpenAIChatClient
from agentkernel.api import RESTAPI
from agentkernel.maf import MAFModule, MAFToolBuilder


def get_weather(location: str) -> str:
    """Get the current weather for a location."""
    return f"The weather in {location} is 72 degrees and sunny."


client = OpenAIChatClient(model="gpt-4o-mini")

maf_agent = Agent(
    client,
    instructions="You are a helpful support agent. Use the tools provided.",
    name="support",
    tools=MAFToolBuilder.bind([get_weather]),
)

MAFModule([maf_agent])

if __name__ == "__main__":
    RESTAPI.run()
