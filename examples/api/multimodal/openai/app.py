from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agents import Agent, ModelSettings

from openai.types.shared import Reasoning

general_agent = Agent(
    name="general",
    instructions="You provide assistance with general queries. Give short and clear answers",
    model="openai/gpt-6-luna",
    model_settings=ModelSettings(reasoning=Reasoning(effort="none")),
)

OpenAIModule([general_agent])

if __name__ == "__main__":
    RESTAPI.run()
