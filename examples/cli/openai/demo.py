from agentkernel.cli import CLI
# from agentkernel.core import ToolContext
from agentkernel.openai import OpenAIModule, OpenAIToolBuilder
from agents import Agent


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
    handoff_description="Specialist agent for math questions",
    instructions="You provide help with math problems. Give short and direct answers exactly to the question. "
    "Don't provide any explanations nor additional details.",
)

general_agent = Agent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and direct answers exactly to the question. "
    "Don't provide any explanations nor additional details",
)

weather_agent = Agent(
    name="weather",
    instructions="You provide weather information upon request. Use the get_weather tool for all weather-related questions.",
    tools=OpenAIToolBuilder.bind([get_weather]),
)

triage_agent = Agent(
    name="triage",
    instructions="You determine which agent to use based on the user's question. Give short and direct answers exactly to the question. "
    "Don't provide any explanations nor additional details",
    handoffs=[general_agent, math_agent, weather_agent],
)

OpenAIModule([triage_agent, math_agent, general_agent, weather_agent])

if __name__ == "__main__":
    CLI.main()
