"""Agent runner entrypoint: polls the Input Queue, runs the agent, sends to the Output Queue.

Nothing here mentions scheduling. The `schedule` block in config.yaml is the whole switch — it
makes this process both the one that executes a fired occurrence (an occurrence arrives on the
Input Queue as a plain chat request) and the one that registers new tasks, whether the request
carried a `schedule` block or the agent called `create_schedule` itself.
"""

from agentkernel.aws import ECSAgentRunner
from agentkernel.openai import OpenAIModule
from agents import Agent

reminder_agent = Agent(
    name="assistant",
    instructions="You are a helpful assistant. When the user asks for something to happen later or on a "
    "recurring basis, register it with the scheduling tools rather than answering as if it had "
    "already run, and tell the user the task id you registered. When a scheduled prompt reaches "
    "you, answer it normally — it is a plain request.",
)

OpenAIModule([reminder_agent])

handler = ECSAgentRunner.run

if __name__ == "__main__":
    handler()
