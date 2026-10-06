from agent_framework import Agent
from agent_framework_openai import OpenAIChatClient
from agentkernel.api import RESTAPI
from agentkernel.maf import MAFModule

# Requires OPENAI_API_KEY
client = OpenAIChatClient(model="gpt-4o-mini")

storyteller_agent = Agent(
    client,
    name="storyteller",
    description="Agent that writes short stories, token-streamed to the client",
    instructions="You are a storyteller. Write a short story of four to six sentences about the topic the user gives you.",
)

MAFModule([storyteller_agent])

# REST API entry point.
runner = RESTAPI.run

if __name__ == "__main__":
    runner()
