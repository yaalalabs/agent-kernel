from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule, OpenAIToolBuilder
from agentkernel.secret import SecretManager
from agents import Agent, OpenAIResponsesModel
from openai import AsyncOpenAI

openai_api_key = SecretManager.current().get("OPENAI_API_KEY")

# Create an agent-scoped client without setting a process-wide OpenAI API key.
openai_client = AsyncOpenAI(api_key=openai_api_key)


def get_weather(city: str) -> str:
    """Returns the weather for a given city from the (stub) weather service."""
    # Optional secret: default=None returns None when the key is unavailable instead of raising.
    # This lets the tool degrade gracefully. SecretManager caches the value after the first lookup.
    api_key = SecretManager.current().get("WEATHER_API_KEY", default=None)

    if api_key is None:
        return "The weather service is not configured: WEATHER_API_KEY is not set."

    if city == "Tokyo":
        return "The weather in Tokyo is sunny."

    return f"Cannot find weather for {city}."


weather_agent = Agent(
    name="weather",
    instructions=(
        "You provide weather information upon request. "
        "Use the get_weather tool for all weather-related questions "
        "and repeat its answer verbatim."
    ),
    tools=OpenAIToolBuilder.bind([get_weather]),
    # The OpenAI client is attached directly to the model, so no `openai/` provider prefix is needed.
    model=OpenAIResponsesModel(
        model="gpt-4.1-mini",
        openai_client=openai_client,
    ),
)

OpenAIModule([weather_agent])


if __name__ == "__main__":
    CLI.main()
