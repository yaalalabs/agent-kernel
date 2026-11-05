"""A smolagents agent token-streamed over SSE through the Agent Kernel REST API."""

from agentkernel.api import RESTAPI
from agentkernel.smolagents import SmolagentsModule
from smolagents import LiteLLMModel, ToolCallingAgent

model = LiteLLMModel(model_id="openai/gpt-4.1-mini")

storyteller_agent = ToolCallingAgent(
    tools=[],
    model=model,
    name="storyteller",
    description=(
        "Agent that writes short stories, token-streamed to the client. Write a short story of "
        "four to six sentences about the topic the user gives you."
    ),
)

SmolagentsModule(agents=[storyteller_agent])

runner = RESTAPI.run

if __name__ == "__main__":
    runner()
