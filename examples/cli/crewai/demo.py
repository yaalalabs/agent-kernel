from agentkernel.cli import CLI
from agentkernel.crewai import CrewAIModule

from crewai import Agent

math_agent = Agent(
    role="math",
    goal="Specialist agent for math questions",
    backstory="You provide help with math problems. Give direct and short answers. Don't give explanations nor additional details. \
        If prompted for anything else you refuse to answer.",
    verbose=False,
)

general_agent = Agent(
    role="general",
    goal="Agent for general questions",
    backstory="You provide assistance with general queries. Give direct and short answers. Don't give explanations nor additional details",
    verbose=False,
)

CrewAIModule([general_agent, math_agent])

if __name__ == "__main__":
    CLI.main()
