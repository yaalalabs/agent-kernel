from agentkernel.cli import CLI
from agentkernel.langgraph import LangGraphModule
from langchain_openai import ChatOpenAI
from langgraph_supervisor import create_supervisor

from custom_agent import CustomAgent
from langgraph.prebuilt import create_react_agent

model = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)

# Math agent: Handles mathematical problems and calculations
# Uses LangGraph's ReAct framework to provide step-by-step mathematical solutions
math_agent = create_react_agent(
    name="math",
    tools=[],
    model=model,
    prompt="You provide help with math problems. Explain your reasoning at each step and include examples. \
        If prompted for anything else you refuse to answer.",
)

# General agent: General agent for all queries
# Uses custom implementation to provide detailed explanations
general_agent = CustomAgent(
    name="general",
    description="Agent for general questions",
    model=model,
    system_prompt="You provide assistance with general queries. Give short and direct answers.",
).graph

# LangGraph's inbuilt supervisor agent: Coordinates between math and general agents
# Routes queries to the appropriate specialized agent based on the question type
triage_agent = create_supervisor(
    model=model,
    agents=[math_agent, general_agent],
    prompt=(
        "You are a supervisor managing two agents:\n"
        "- a math agent. Assign math-related tasks to this agent\n"
        "- a general agent. Assign general tasks to this agent\n"
        "Assign work to one agent at a time, do not call agents in parallel.\n"
        "Do not do any work yourself. \n"
        "Display the response without asking follow up questions."
    ),
).compile(name="triage")

LangGraphModule([triage_agent, math_agent, general_agent])

if __name__ == "__main__":
    CLI.main()
