from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agentkernel.teams import AgentTeamsRequestHandler
from agents import Agent as OpenAIAgent

general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and clear answers",
)

OpenAIModule([general_agent])


if __name__ == "__main__":
    RESTAPI.run([AgentTeamsRequestHandler()])
