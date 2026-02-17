from agentkernel.cli import CLI
from agentkernel.core import ToolContext
from agentkernel.langgraph import LangGraphModule, LangGraphToolBuilder
from langchain_openai import ChatOpenAI
from langgraph_supervisor import create_supervisor

from custom_agent import CustomAgent
from langgraph.prebuilt import create_react_agent

model = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)


def get_weather(city: str) -> str:
    """Returns the weather for a given city (example stub)."""
    print(ToolContext.get().session.id)
    print(ToolContext.get().agent.name)
    print(ToolContext.get().requests)

    if city == "Tokyo":
        return "The weather in Tokyo is sunny."
    else:
        return f"Cannot find weather for {city}."


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

# Weather agent: Handles weather-related queries using the get_weather tool
# Uses LangGraph's ReAct framework with a bound tool function
weather_agent = create_react_agent(
    name="weather",
    tools=LangGraphToolBuilder.bind([get_weather]),
    model=model,
    prompt="You provide weather information upon request. Use only the get_weather tool for all weather-related questions.",
)

# LangGraph's inbuilt supervisor agent: Coordinates between math, general, and weather agents
# Routes queries to the appropriate specialized agent based on the question type
triage_agent = create_supervisor(
    model=model,
    agents=[math_agent, general_agent, weather_agent],
    prompt=(
        "You are a supervisor managing three agents:\n"
        "- a math agent. Assign math-related tasks to this agent\n"
        "- a general agent. Assign general tasks to this agent\n"
        "- a weather agent. Assign weather-related tasks to this agent\n"
        "Assign work to one agent at a time, do not call agents in parallel.\n"
        "Do not do any work yourself. \n"
        "Display the response without asking follow up questions."
    ),
).compile(name="triage")

LangGraphModule([triage_agent, math_agent, general_agent, weather_agent])

if __name__ == "__main__":
    CLI.main()
