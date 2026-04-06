from agentkernel.api import RESTAPI
from agentkernel.crewai import CrewAIModule

from crewai import Agent

general_agent = Agent(
    role="general",
    goal="Assistant with general queries",
    backstory="You provide assistance with general queries. Give short and clear answers",
    verbose=False,
)

CrewAIModule([general_agent])

if __name__ == "__main__":
    RESTAPI.run()
