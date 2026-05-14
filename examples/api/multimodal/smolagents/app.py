from agentkernel.api import RESTAPI
from agentkernel.smolagents import SmolagentsModule

from smolagents import LiteLLMModel, ToolCallingAgent

model = LiteLLMModel(model_id="openai/gpt-4o")

general_agent = ToolCallingAgent(
    tools=[],
    model=model,
    name="general",
    description="You provide assistance with general queries. Give short and clear answers.",
)

SmolagentsModule([general_agent])

if __name__ == "__main__":
    RESTAPI.run()
