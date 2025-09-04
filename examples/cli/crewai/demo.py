from crewai import Agent

from ak.cli import CLI
from ak.crewai import CrewAIModule

math_agent = Agent(
    role="math",
    goal="Specialist agent for math questions",
    backstory="You provide help with math problems. Explain your reasoning at each step and include examples. \
        If prompted for anything else you refuse to answer.",
    verbose=False,
)

general_agent = Agent(
    role="general",
    goal="Agent for general questions",
    backstory="You provide assistance with general queries. Explain important details and context clearly.",
    verbose=False,
)

CrewAIModule([math_agent, general_agent])

if __name__ == "__main__":
    CLI.main()
