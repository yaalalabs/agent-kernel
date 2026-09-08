from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agentkernel.smolagents import SmolagentsModule
from agents import Agent as OpenAIAgent
from smolagents import LiteLLMModel, ToolCallingAgent

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

history_agent = ToolCallingAgent(
    tools=[],
    model=LiteLLMModel(model_id="openai/gpt-4.1-mini"),
    name="history",
    description="Specialist agent for history questions. You provide assistance with history queries. "
    "Give direct and correct answers. Answer the question only. Don't give any explanation",
)

OpenAIModule([general_agent, math_agent])
SmolagentsModule([history_agent])

if __name__ == "__main__":
    RESTAPI.run()
