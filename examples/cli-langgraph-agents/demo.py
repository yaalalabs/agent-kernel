import os
from langgraph.prebuilt import create_react_agent
from langgraph_supervisor import create_supervisor
from langchain_openai import ChatOpenAI
from ak import CLI
from ak_langgraph import AgentModule, AgentSession
from custom_langgraph_agent import CustomLangGraphAgent

session = AgentSession()

model = ChatOpenAI(model_name="gpt-4o-mini", temperature=0.0, openai_api_key=os.getenv("OPENAI_API_KEY"))

math_agent = create_react_agent(
    name="math",
    tools=[],
    model=model,
    prompt="You provide help with math problems. Explain your reasoning at each step and include examples. \
        If prompted for anything else you refuse to answer.",
)

history_agent = CustomLangGraphAgent(
    name="history",
    description="Specialist agent for historical questions",
    model=model,    
    system_prompt="You provide assistance with historical queries. Explain important events and context clearly.",
).graph

supervisor = create_supervisor(
    model=model,
    agents=[history_agent, math_agent],
    prompt=(
        "You are a supervisor managing two agents:\n"
        "- a history agent. Assign history-related tasks to this agent\n"
        "- a math agent. Assign math-related tasks to this agent\n"
        "Assign work to one agent at a time, do not call agents in parallel.\n"
        "Do not do any work yourself."
    )
).compile(name="supervisor", checkpointer=session.checkpointer)

AgentModule([supervisor, history_agent, math_agent])

if __name__ == "__main__":
    CLI.main()
