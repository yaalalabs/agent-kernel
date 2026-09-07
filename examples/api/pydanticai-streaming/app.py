from agentkernel.api import RESTAPI
from agentkernel.pydanticai import PydanticAIModule
from pydantic_ai import Agent

# Provider-agnostic: swap for "anthropic:...", "google-gla:...", etc. (install the matching provider
# extra, e.g. pydantic-ai-slim[anthropic]). Requires OPENAI_API_KEY for the model below.
MODEL = "openai:gpt-4.1-mini"

storyteller_agent = Agent(
    model=MODEL,
    name="storyteller",
    description="Agent that writes short stories, token-streamed to the client",
    instructions="You are a storyteller. Write a short story of four to six sentences about the topic "
    "the user gives you.",
)

PydanticAIModule([storyteller_agent])

# Entry point referenced by the Dockerfile (from app import runner; runner()).
runner = RESTAPI.run

if __name__ == "__main__":
    runner()
