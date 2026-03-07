from agentkernel.aws import Lambda
from agentkernel.openai import OpenAIModule
from agents import Agent

general_agent = Agent(
    name="general",
    instructions="You provide assistance with general queries. Give short and clear answers",
)

OpenAIModule([general_agent])

handler = Lambda.handler
