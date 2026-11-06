"""A CrewAI agent token-streamed over SSE through the Agent Kernel REST API."""

from agentkernel.api import RESTAPI
from agentkernel.crewai import CrewAIModule
from crewai import Agent

storyteller_agent = Agent(
    role="storyteller",
    goal="Write short stories about the topic the user gives you.",
    backstory="You are a storyteller. Write a short story of four to six sentences about the topic the user gives you.",
    verbose=False,
    llm="openai/gpt-4.1-mini",
)

CrewAIModule([storyteller_agent])

runner = RESTAPI.run

if __name__ == "__main__":
    runner()
