import logging

from agentkernel.cli import CLI
from agentkernel.core import ToolContext
from agentkernel.framework.autogen import AutogenModule, AutogenToolBuilder

import autogen


def get_weather(city: str) -> str:
    """Returns the weather for a given city (example stub)."""
    logger = logging.getLogger(__name__)
    if ToolContext.get() and ToolContext.get().session:
        logger.debug(f"Session ID: {ToolContext.get().session.id}")

    if city == "Tokyo":
        return "The weather in Tokyo is sunny."
    else:
        return f"Cannot find weather for {city}."


# Setup LLM configuration
llm_config = {"config_list": [{"model": "gpt-4o", "api_type": "openai"}]}

math_agent = autogen.ConversableAgent(
    name="math",
    system_message="You are a specialist agent for math questions. You provide help with math problems. Give direct and short answers. Don't give explanations nor additional details.",
    llm_config=llm_config,
    human_input_mode="NEVER",
)

general_agent = autogen.ConversableAgent(
    name="general",
    system_message="You are an agent for general questions. You provide assistance with general queries. Give direct and short answers. Don't give explanations nor additional details.",
    llm_config=llm_config,
    human_input_mode="NEVER",
)

weather_agent = autogen.ConversableAgent(
    name="weather",
    system_message="You provide weather information upon request. Use the get_weather tool for all weather-related questions.",
    llm_config=llm_config,
    human_input_mode="NEVER",
)

# Load agents into the module
module = AutogenModule(agents=[general_agent, math_agent, weather_agent])

# Attach the tool to the weather agent using standard AgentKernel API
module.get_agent("weather").attach_tool(get_weather)

if __name__ == "__main__":
    CLI.main()
