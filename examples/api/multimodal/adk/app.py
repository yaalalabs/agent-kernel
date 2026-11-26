from agentkernel.adk import GoogleADKModule
from agentkernel.api import RESTAPI
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

general_agent = Agent(
    name="general",
    model=LiteLlm(model="openai/gpt-6-luna", reasoning_effort="none"),
    description="Assistant with general queries",
    instruction="You provide assistance with general queries. Give short and clear answers",
)

GoogleADKModule([general_agent])

if __name__ == "__main__":
    RESTAPI.run()
