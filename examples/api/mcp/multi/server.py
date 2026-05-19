from agentkernel.api import RESTAPI
from agentkernel.mcp import MCP
from agentkernel.openai import OpenAIModule
from agentkernel.smolagents import SmolagentsModule
from agents import Agent as OpenAIAgent
from smolagents import LiteLLMModel, ToolCallingAgent

model = LiteLLMModel(model_id="openai/gpt-4o")

general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and clear answers. "
    "Give direct and correct answers. Answer the question only. Don't give any explanation",
)

math_agent = OpenAIAgent(
    name="math",
    handoff_description="Specialist agent for math questions",
    instructions="You provide help with math problems. Give direct and correct answers. Answer the question only. Don't give any explanation. \
        If prompted for anything else you refuse to answer.",
)

history_agent = ToolCallingAgent(
    tools=[],
    model=model,
    name="history",
    description="You provide assistance with history queries. Give direct and correct answers. Answer the question only. Don't give any explanation",
)

OpenAIModule([general_agent, math_agent])
SmolagentsModule([history_agent])

mcp = MCP.get()


@mcp.tool
def agent_kernel_knowledge(prompt: str, session_id: str):
    """Dummy tool to test MCP"""
    return "Agent Kernel supports both MCP and A2A"


if __name__ == "__main__":
    RESTAPI.run()
