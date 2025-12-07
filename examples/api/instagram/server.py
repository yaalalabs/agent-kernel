from agentkernel.api import RESTAPI
from agentkernel.instagram import AgentInstagramRequestHandler
from agentkernel.openai import OpenAIModule
from agents import Agent as OpenAIAgent

# Create your agent
general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and clear answers suitable for Instagram DMs.",
)

# Initialize module with agent
OpenAIModule([general_agent])


if __name__ == "__main__":
    handler = AgentInstagramRequestHandler()
    RESTAPI.run([handler])
