from agentkernel.adk import GoogleADKModule, GoogleADKToolBuilder
from agentkernel.cli import CLI

# from agentkernel.core import ToolContext
from google.adk.agents import Agent, LlmAgent
from google.adk.models.lite_llm import LiteLlm


def get_weather(city: str) -> str:
    """Returns the weather for a given city (example stub)."""
    # print(ToolContext.get().session.id)
    # print(ToolContext.get().agent.name)
    # print(ToolContext.get().requests)

    if city == "Tokyo":
        return "The weather in Tokyo is sunny."
    else:
        return f"Cannot find weather for {city}."


math_agent = Agent(
    name="math",
    model=LiteLlm(model="openai/gpt-4o-mini"),
    description="Specialist agent for math questions",
    instruction="""
    You provide help with math problems.
    Explain your reasoning at each step and include examples.
    If prompted for anything else you refuse to answer.
    """,
)

history_agent = Agent(
    name="history",
    model=LiteLlm(model="openai/gpt-4o-mini"),
    description="Agent for history questions",
    instruction="""
    You provide assistance with history queries.
    Give short and direct answers.
    """,
)

weather_agent = Agent(
    name="weather",
    model=LiteLlm(model="openai/gpt-4o-mini"),
    description="You provide weather information upon request",
    instruction="""
    You provide weather information upon request. Use the get_weather tool for all weather-related questions.
    """,
    tools=GoogleADKToolBuilder.bind([get_weather]),
)

triage_agent = LlmAgent(
    name="triage",
    model=LiteLlm(model="openai/gpt-4o-mini"),
    description="Agent that routes the user to the appropriate specialist agent (math or history).",
    instruction="""
    You determine which agent to use based on the user's question.
    If it's a math problem, issue an action.transfer_to_agent to the agent named "math".
    Otherwise, if it's history related query, transfer to "history".
    """,
    sub_agents=[history_agent, math_agent, weather_agent],
)

GoogleADKModule([triage_agent, math_agent, history_agent, weather_agent])

if __name__ == "__main__":
    CLI.main()
