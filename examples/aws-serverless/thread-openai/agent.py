"""The agent, imported by the agent-runner Lambda only: the request handler holds no agents."""

from agentkernel.openai import OpenAIModule
from agents import Agent

assistant = Agent(
    name="assistant",
    instructions="You are a helpful assistant. Give short and direct answers.",
    model="openai/gpt-4.1-mini",
)

OpenAIModule([assistant])
