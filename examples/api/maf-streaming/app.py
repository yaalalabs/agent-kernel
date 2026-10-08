from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient
from agentkernel.api import RESTAPI
from agentkernel.maf import MAFModule

client = OpenAIChatClient(model="gpt-4o-mini")

storyteller_agent = Agent(
    client,
    name="storyteller",
    description="Agent that writes short stories, token-streamed to the client",
    instructions="You are a storyteller. Write a short story of four to six sentences about the topic the user gives you.",
)

MAFModule([storyteller_agent])

if __name__ == "__main__":
    RESTAPI.run()
