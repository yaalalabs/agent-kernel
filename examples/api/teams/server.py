from agentkernel.integration.adapter import WebhookRESTRequestHandler
from agentkernel.openai import OpenAIModule
from agentkernel.pipeline import IOHandler
from agentkernel.teams import TeamsInboundAdapter
from agents import Agent as OpenAIAgent

general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and clear answers",
)

OpenAIModule([general_agent])


if __name__ == "__main__":
    IOHandler.run(handlers=[WebhookRESTRequestHandler(TeamsInboundAdapter())])
