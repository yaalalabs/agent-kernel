from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule
from agents import Agent, ModelSettings
from openai.types.shared import Reasoning

# The sandbox capability injects its own context (available tools, session reuse,
# workload profiles) into every agent's system prompt when enabled — the agent's
# instructions stay free of sandbox internals.
coder_agent = Agent(
    name="coder",
    instructions="You are a coding assistant. Give short, direct answers backed by what you actually executed.",
    model="openai/gpt-6-luna",
    model_settings=ModelSettings(reasoning=Reasoning(effort="none")),
)

OpenAIModule([coder_agent])

if __name__ == "__main__":
    CLI.main()
