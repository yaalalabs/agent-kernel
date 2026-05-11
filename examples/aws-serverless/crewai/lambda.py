import os

from agentkernel.aws import Lambda
from agentkernel.crewai import CrewAIModule

os.environ["CREWAI_TRACING_ENABLED"] = "false"

from crewai import Agent

math_agent = Agent(
    role="math",
    goal="Specialist agent for math questions",
    backstory="You provide help with math problems. no reasoning and no need for steps explanation. Just give the final answer. \
        If prompted for anything else you refuse to answer.",
    verbose=False,
    tracing=False,
    model="openai/gpt-4.1-2025-04-14",
)

history_agent = Agent(
    role="history",
    goal="Specialist agent for historical questions",
    backstory="You provide assistance with historical queries. Explain important events and context clearly.",
    verbose=False,
    tracing=False,
    model="openai/gpt-4.1-2025-04-14",
)

CrewAIModule([math_agent, history_agent])

handler = Lambda.handler
