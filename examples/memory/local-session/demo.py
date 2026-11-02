"""Minimal API app whose conversation memory follows config.yaml.

With the default in_memory backend a restart forgets the conversation. Switch
config.yaml to Redis (or Valkey) and repeat the same requests to see the
conversation survive a restart.
"""

from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agents import Agent

assistant = Agent(
    name="memory_assistant",
    model="gpt-4.1-mini",
    instructions=("You are a helpful assistant. Remember facts the user tells you and use them in later turns."),
)

OpenAIModule([assistant])

if __name__ == "__main__":
    RESTAPI.run()
