from agentkernel.adk import GoogleADKModule
from agentkernel.api import RESTAPI
from agentkernel.telegram import AgentTelegramRequestHandler
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

# Create your Google ADK agent with correct API
general_agent = Agent(
    name="general",
    model=LiteLlm(model="openai/gpt-4o-mini"),
    description="Agent for general questions",
    instruction="""
    You provide assistance with general queries. 
    Give short and clear answers suitable for Telegram messaging.
    If you receive images or files, analyze them and provide relevant insights.
    """,
)

# Initialize module with agent
GoogleADKModule([general_agent])


if __name__ == "__main__":
    handler = AgentTelegramRequestHandler()
    RESTAPI.run([handler])
