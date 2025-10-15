from agentkernel.api import RESTAPI
from agentkernel.crewai import CrewAIModule
from crewai import Agent

math_agent = Agent(
    role="math",
    goal="Specialist agent for math questions",
    backstory="You provide help with math problems. Explain your reasoning at each step and include examples. \
        If prompted for anything else you refuse to answer.",
    verbose=False,
)

history_agent = Agent(
    role="history",
    goal="Specialist agent for historical questions",
    backstory="You provide assistance with historical queries. Explain important events and context clearly.",
    verbose=False,
)

CrewAIModule([math_agent, history_agent])

runner = RESTAPI.run
