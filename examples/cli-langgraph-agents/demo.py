import os
from dotenv import load_dotenv

from ak import CLI
from ak_langgraph import Agent, AgentModule, AgentRunner, LiteLLMModel

load_dotenv()

llm = LiteLLMModel(model_name="gemini/gemini-2.5-flash", temperature=0.0, api_key=os.getenv("GEMINI_API_KEY"))

math_agent = Agent(
    name="math",
    description="Specialist agent for math questions",
    model=llm,
    system_prompt="You provide help with math problems. Explain your reasoning at each step and include examples. \
        If prompted for anything else you refuse to answer.",
    runner=AgentRunner(),
    # tool_functions=[math_tool],
)

history_agent = Agent(
    name="history",
    description="Specialist agent for historical questions",
    model=llm,
    system_prompt="You provide assistance with historical queries. Explain important events and context clearly.",
    runner=AgentRunner(),
)

triage_agent = Agent(
    name="GeneralAgent",
    description="You determine which agent to use based on the user's question.",
    model=llm,
    system_prompt="You determine which agent to use based on the user's question.",
    runner=AgentRunner(),
    handoffs=[history_agent, math_agent],
)

AgentModule([triage_agent, math_agent, history_agent])

if __name__ == "__main__":
    CLI.main()
