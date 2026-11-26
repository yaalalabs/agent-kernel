from agentkernel.api import RESTAPI
from agentkernel.crewai import CrewAIModule

from crewai import LLM, Agent

general_agent = Agent(
    role="general",
    goal="Assistant with general queries",
    backstory="You provide assistance with general queries. Give short and clear answers",
    verbose=False,
    llm=LLM(model="openai/gpt-6-luna", reasoning_effort="none"),
)

CrewAIModule([general_agent])

if __name__ == "__main__":
    RESTAPI.run()
