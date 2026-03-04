from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agents import Agent

support_agent = Agent(
    name="support",
    instructions="You are an AI assistant that can see and analyze images. "
                 "When a user uploads an image, describe it in detail. "
                 "Remember context from previous messages in the conversation.",
)

OpenAIModule([support_agent])

if __name__ == "__main__":
    RESTAPI.run()
