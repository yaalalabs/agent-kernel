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
    backstory="You provide assistance with general queries. Give direct and short answers",
    verbose=False,
)

CrewAIModule([general_agent, math_agent])

if __name__ == "__main__":
    CLI.main()
