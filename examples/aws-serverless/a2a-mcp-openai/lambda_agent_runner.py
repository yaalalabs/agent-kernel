"""Agent-runner Lambda: consumes the Input Queue, runs the agent, sends to the Output Queue.

Nothing here mentions A2A or MCP. A call from either arrives as a queue message tagged with its protocol; the runner
runs the agent exactly as it does for a chat request, and the reply goes back through the Output Queue to the response
store, where the request handler reads it.
"""

from agentkernel.aws import ServerlessAgentRunner
from agentkernel.openai import OpenAIModule
from agentkernel.secret import SecretManager
from agents import set_default_openai_key

from lambda_agents import assistant

# OPENAI_API_KEY from the environment when set, else from SSM (/ak/<prefix>/openai_api_key). The value is
# handed to the SDK in memory; it is never written back to os.environ.
set_default_openai_key(SecretManager.current().get("OPENAI_API_KEY"))

OpenAIModule([assistant])

handler = ServerlessAgentRunner.handle
