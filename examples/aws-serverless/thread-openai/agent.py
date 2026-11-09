"""The agent, imported by both the agent-runner and the request-handler Lambda.

The request handler needs it too: with threads on, the chat route checks the agent exists before it
writes the user message to the thread.
"""

from agentkernel.openai import OpenAIModule
from agents import Agent

assistant = Agent(
    name="assistant",
    instructions="You are a helpful assistant. Give short and direct answers.",
    model="openai/gpt-4.1-mini",
)

OpenAIModule([assistant])
