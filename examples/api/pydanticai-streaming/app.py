from agentkernel.api import RESTAPI
from agentkernel.pydanticai import PydanticAIModule
from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings

# Provider-agnostic: swap for "anthropic:...", "google-gla:...", etc. (install the matching provider
# extra, e.g. pydantic-ai-slim[anthropic]). Requires OPENAI_API_KEY for the model below.
MODEL = "openai:gpt-6-luna"

storyteller_agent = Agent(
    model=MODEL,
    model_settings=ModelSettings(openai_reasoning_effort="none"),
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
