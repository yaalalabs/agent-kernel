from agentkernel.cli import CLI
from agentkernel.crewai import CrewAIModule
from agentkernel.openai import OpenAIModule
from agents import Agent as OpenAIAgent
from agents import ModelSettings
from crewai import LLM
from crewai import Agent as CrewAIAgent
from openai.types.shared import Reasoning

general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and clear answers",
    model="openai/gpt-6-luna",
    model_settings=ModelSettings(reasoning=Reasoning(effort="none")),
)

math_agent = OpenAIAgent(
    name="math",
    handoff_description="Specialist agent for math questions",
    instructions="You provide help with math problems. Explain your reasoning at each step and include examples. \
        If prompted for anything else you refuse to answer.",
    model="openai/gpt-6-luna",
    model_settings=ModelSettings(reasoning=Reasoning(effort="none")),
)

history_agent = CrewAIAgent(
    role="history",
    goal="Specialist agent for history questions",
    backstory="You provide assistance with history queries. Explain important details and context clearly.",
    verbose=False,
    llm=LLM(model="openai/gpt-6-luna", reasoning_effort="none"),
)

OpenAIModule([general_agent, math_agent])
CrewAIModule([history_agent])

if __name__ == "__main__":
    CLI.main()
