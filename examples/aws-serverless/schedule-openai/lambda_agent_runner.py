"""Agent-runner Lambda: consumes the Input Queue, runs the agent, sends to the Output Queue.

Nothing here mentions scheduling. The `schedule` block in config.yaml is the whole switch — it
makes this function both the one that executes a fired occurrence (an occurrence arrives on the
Input Queue as a plain chat request) and the one that registers new tasks, whether the request
carried a `schedule` block or the agent called `create_schedule` itself.
"""

from agentkernel.aws import ServerlessAgentRunner
from agentkernel.openai import OpenAIModule
from agentkernel.secret import SecretManager
from agents import Agent, set_default_openai_key

# OPENAI_API_KEY from the environment when set, else from SSM (/ak/<prefix>/openai_api_key). The value is
# handed to the SDK in memory; it is never written back to os.environ.
set_default_openai_key(SecretManager.current().get("OPENAI_API_KEY"))

reminder_agent = Agent(
    name="assistant",
    instructions="You are a helpful assistant. When the user asks for something to happen later or on a "
    "recurring basis, register it with the scheduling tools rather than answering as if it had "
    "already run, and tell the user the task id you registered. When a scheduled prompt reaches "
    "you, answer it normally — it is a plain request.",
    model="openai/gpt-4.1-mini",
)

OpenAIModule([reminder_agent])

handler = ServerlessAgentRunner.handle
