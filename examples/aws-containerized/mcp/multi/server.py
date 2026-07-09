from agentkernel.api import RESTAPI
from agentkernel.crewai import CrewAIModule
from agentkernel.mcp import MCP
from agentkernel.openai import OpenAIModule
from agents import Agent as OpenAIAgent
from crewai import Agent as CrewAIAgent

general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and clear answers. "
    "Give direct and correct answers. Answer the question only. Don't give any explanation",
    model="openai/gpt-4.1-mini",
)

math_agent = OpenAIAgent(
    name="math",
    handoff_description="Specialist agent for math questions",
    instructions="You provide help with math problems. Do not provide reasoning or step-by-step explanations. Just give the final answer. \
         If prompted for anything else, refuse to answer.",
    model="openai/gpt-4.1-mini",
)

history_agent = CrewAIAgent(
    role="history",
    goal="Specialist agent for history questions",
    backstory="You provide assistance with history queries. Give direct and correct answers. Answer the question only. Don't give any explanation",
    verbose=False,
    model="openai/gpt-4.1-mini",
)

OpenAIModule([general_agent, math_agent])
CrewAIModule([history_agent])

mcp = MCP.get()


@mcp.tool
def agent_kernel_knowledge(prompt: str, session_id: str):
    """Dummy tool to test MCP"""
    return "Agent Kernel supports both MCP and A2A"


runner = RESTAPI.run
