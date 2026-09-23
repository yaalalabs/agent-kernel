from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule, OpenAIToolBuilder
from agentkernel.secret import SecretManager
from agents import Agent, set_default_openai_key

# Resolve the model key through the secret capability and hand it to the SDK in memory. With
# `secret.provider.type: env` (config.yaml) it comes from OPENAI_API_KEY; a missing key fails here,
# at startup, with SecretNotFoundError rather than on the first model call.
set_default_openai_key(SecretManager.current().get("OPENAI_API_KEY"))


def get_weather(city: str) -> str:
    """Returns the weather for a given city from the (stub) weather service."""
    # An optional secret: `default=None` turns a miss into None instead of raising, so the tool can
    # degrade gracefully. Resolved per call, served from the process cache after the first read.
    api_key = SecretManager.current().get("WEATHER_API_KEY", default=None)
    if api_key is None:
        return "The weather service is not configured: WEATHER_API_KEY is not set."

    if city == "Tokyo":
        return "The weather in Tokyo is sunny."
    return f"Cannot find weather for {city}."


weather_agent = Agent(
    name="weather",
    instructions="You provide weather information upon request. Use the get_weather tool for all weather-related "
    "questions and repeat its answer verbatim.",
    tools=OpenAIToolBuilder.bind([get_weather]),
    model="openai/gpt-4.1-mini",
)

OpenAIModule([weather_agent])

if __name__ == "__main__":
    CLI.main()
