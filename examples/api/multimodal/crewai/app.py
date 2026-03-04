from agentkernel.api import RESTAPI
from agentkernel.crewai import CrewAIModule

from crewai import Agent

support_agent = Agent(
    role="support",
    goal="Assistant that can analyze images",
    backstory="You are an AI assistant that can see and analyze images. "
    "When a user uploads an image, describe it in detail. "
    "Remember context from previous messages in the conversation.",
    verbose=False,
)

CrewAIModule([support_agent])

if __name__ == "__main__":
    RESTAPI.run()
