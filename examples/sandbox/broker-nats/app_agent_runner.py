"""The runner process: consumes the input queue and executes the agents.

This is the entry point behind the chart's agent-runner Deployment. The sandbox capability is
enabled in config.yaml, so Agent Kernel attaches the sandbox tools and their usage guidance
automatically; sandbox executions leave this pod as queue messages (the 'queue' broker
flavor) and run in pods the sandbox worker creates. The REST side lives in app_io_handler.py.
"""

from agentkernel.openai import OpenAIModule
from agentkernel.pipeline import AgentRunner
from agents import Agent

coder_agent = Agent(
    name="coder",
    instructions="You are a coding assistant. Run the user's computations in the sandbox and answer "
    "only from what actually executed. Follow the user's output-format instructions exactly.",
    model="openai/gpt-4.1-mini",
)

OpenAIModule([coder_agent])


def main():
    AgentRunner.run()


if __name__ == "__main__":
    main()
