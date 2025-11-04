from agentkernel.aws import Lambda
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

# History agent: Specialized in handling historical queries
# Uses custom implementation to provide detailed historical context and explanations
history_agent = CustomAgent(
    name="history",
    description="Specialist agent for historical questions",
    model=model,
    system_prompt="You provide assistance with historical queries. Explain important events and context clearly.",
).graph

# LangGraph's inbuilt supervisor agent: Coordinates between math and history agents
# Routes queries to the appropriate specialized agent based on the question type
triage_agent = create_supervisor(
    model=model,
    agents=[history_agent, math_agent],
    prompt=(
        "You are a supervisor managing two agents:\n"
        "- a history agent. Assign history-related tasks to this agent\n"
        "- a math agent. Assign math-related tasks to this agent\n"
        "Assign work to one agent at a time, do not call agents in parallel.\n"
        "Do not do any work yourself. \n"
        "When you get a response from an agent, respond with the received response."
    ),
).compile(name="triage")

LangGraphModule([triage_agent, history_agent, math_agent])

handler = Lambda.handler
