import logging

from agentkernel.cli import CLI
from agentkernel.crewai import CrewAIModule, CrewAIToolBuilder

from crewai import Agent


def get_weather(city: str) -> str:
    """Returns the weather for a given city (example stub)."""
    logger = logging.getLogger(__name__)
    logger.debug("Session ID: %s", ToolContext.get().session.id)    

    if city == "Tokyo":
        return "The weather in Tokyo is sunny."
    else:
        return f"Cannot find weather for {city}."


math_agent = Agent(
    role="math",
    goal="Specialist agent for math questions",
    backstory="You provide help with math problems. Give direct and short answers. Don't give explanations nor additional details. \
        If prompted for anything else you refuse to answer.",
    verbose=False,
)

general_agent = Agent(
    role="general",
    goal="Agent for general questions",
    backstory="You provide assistance with general queries. Give direct and short answers. Don't give explanations nor additional details",
    verbose=False,
)

weather_agent = Agent(
    role="weather",
    goal="You provide weather information upon request",
    backstory="You provide weather information upon request. Use the get_weather tool for all weather-related questions.",
    tools=CrewAIToolBuilder.bind([get_weather]),
    verbose=False,
)

CrewAIModule([general_agent, math_agent, weather_agent])

if __name__ == "__main__":
    CLI.main()
