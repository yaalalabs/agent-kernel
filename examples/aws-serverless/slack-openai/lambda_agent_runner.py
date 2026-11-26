"""Agent-runner Lambda: consumes the Input Queue, runs the agent, sends to the Output Queue.

Nothing here mentions Slack. A Slack message arrives as a queue message carrying its return
address (the `integration` attribute plus the `reply_*` context); the runner passes that on to the
Output Queue with the reply, and the response handler delivers it to Slack.
"""

from agentkernel.aws import ServerlessAgentRunner
from agentkernel.openai import OpenAIModule
from agentkernel.secret import SecretManager
from agents import Agent, ModelSettings, set_default_openai_key
from openai.types.shared import Reasoning

# OPENAI_API_KEY from the environment when set, else from SSM (/ak/<prefix>/openai_api_key). The value is
# handed to the SDK in memory; it is never written back to os.environ.
set_default_openai_key(SecretManager.current().get("OPENAI_API_KEY"))

assistant = Agent(
    name="assistant",
    instructions="You are a helpful assistant in a Slack workspace. Give short, clear answers.",
    model="openai/gpt-6-luna",
    model_settings=ModelSettings(reasoning=Reasoning(effort="none")),
)

OpenAIModule([assistant])

handler = ServerlessAgentRunner.handle
