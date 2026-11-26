from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient
from agentkernel.api import RESTAPI
from agentkernel.maf import MAFModule

client = OpenAIChatClient(model="gpt-6-luna")

storyteller_agent = Agent(
    client,
    default_options={"reasoning": {"effort": "none"}},
    name="storyteller",
    description="Agent that writes short stories, token-streamed to the client",
    instructions="You are a storyteller. Write a short story of four to six sentences about the topic the user gives you.",
)

MAFModule([storyteller_agent])

# Entry point referenced by the Dockerfile (from app import runner; runner()).
runner = RESTAPI.run

if __name__ == "__main__":
    runner()
