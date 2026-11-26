from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule
from agents import Agent, ModelSettings
from openai.types.shared import Reasoning

trivia_agent = Agent(
    name="trivia",
    instructions="You are a trivia assistant. Give short and direct answers exactly to the question. "
    "Don't provide any explanations nor additional details.",
    model="openai/gpt-6-luna",
    model_settings=ModelSettings(reasoning=Reasoning(effort="none")),
)

OpenAIModule([trivia_agent])

if __name__ == "__main__":
    CLI.main()
