from agentkernel.api import RESTAPI
from agentkernel.adk import GoogleADKModule
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

support_agent = Agent(
    name="support",
    model=LiteLlm(model="openai/gpt-4o-mini"),
    description="Assistant that can analyze images",
    instruction="You are an AI assistant that can see and analyze images. "
                 "When a user uploads an image, describe it in detail. "
                 "Remember context from previous messages in the conversation.",
)

GoogleADKModule([support_agent])

if __name__ == "__main__":
    RESTAPI.run()
