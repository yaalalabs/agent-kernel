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
    When users send images or files, analyze them and remember them for follow-up questions.
    """,
)

# Initialize module with agent (multimodal hooks auto-registered)
GoogleADKModule([general_agent])


if __name__ == "__main__":
    print("Starting Telegram bot with Google ADK framework...")
    print("Multimodal memory: ENABLED (images/files will be remembered)")
    handler = AgentTelegramRequestHandler()
    RESTAPI.run([handler])
