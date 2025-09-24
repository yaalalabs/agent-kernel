from agents import Agent as OpenAIAgent
from ak.api import RESTAPI
from ak.crewai import CrewAIModule
from ak.openai import OpenAIModule
from crewai import Agent as CrewAIAgent

general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and clear answers",
)

math_agent = OpenAIAgent(
    name="math",
    handoff_description="Specialist agent for math questions",
    instructions="You provide help with math problems. Explain your reasoning at each step and include examples. \
        If prompted for anything else you refuse to answer.",
)

history_agent = CrewAIAgent(
    role="history",
    goal="Specialist agent for history questions",
    backstory="You provide assistance with history queries. Give direct and correct answers. Answer the question only. Don't give any explanation",
    verbose=False,
)

OpenAIModule([general_agent, math_agent])
CrewAIModule([history_agent])

if __name__ == "__main__":
    RESTAPI.run()
