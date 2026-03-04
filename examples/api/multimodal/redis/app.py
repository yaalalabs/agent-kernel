from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agents import Agent

support_agent = Agent(
    name="support",
    instructions="You provide assistance with general queries. Give short and direct answers.",
)

OpenAIModule([support_agent])

if __name__ == "__main__":
    RESTAPI.run()
