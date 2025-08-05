import os
from dotenv import load_dotenv

from ak import CLI
from ak_langgraph import AgentModule, AgentSession

from langgraph_custom_agent import LangGraphAgent, LiteLLMModel

load_dotenv()

session = AgentSession()

llm = LiteLLMModel(model_name="gemini/gemini-2.5-flash", temperature=0.0, api_key=os.getenv("GEMINI_API_KEY"))

math_agent = LangGraphAgent(
    name="math",
    description="Specialist agent for math questions",
    model=llm,
    system_prompt="You provide help with math problems. Explain your reasoning at each step and include examples. \
        If prompted for anything else you refuse to answer.",
    # tool_functions=[math_tool],
)

history_agent = LangGraphAgent(
    name="history",
    description="Specialist agent for historical questions",
    model=llm,
    system_prompt="You provide assistance with historical queries. Explain important events and context clearly.",
)

triage_agent = LangGraphAgent(
    name="GeneralAgent",
    description="You determine which agent to use based on the user's question.",
    model=llm,
    system_prompt="You determine which agent to use based on the user's question.",
    handoffs=[history_agent, math_agent],
    checkpointer=session.checkpointer
)

AgentModule([triage_agent.graph, math_agent.graph, history_agent.graph])

if __name__ == "__main__":
    CLI.main()
