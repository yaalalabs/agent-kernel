from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule
from agents import Agent

trivia_agent = Agent(
    name="trivia",
    instructions="You are a trivia assistant. Give short and direct answers exactly to the question. "
    "Don't provide any explanations nor additional details.",
)

OpenAIModule([trivia_agent])

if __name__ == "__main__":
    CLI.main()
