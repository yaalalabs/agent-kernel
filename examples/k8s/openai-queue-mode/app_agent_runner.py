"""The runner process: consumes the input queue and executes the agents.

This is the entry point behind the chart's agent-runner Deployment. It loads the agents
(app_agents.py, shared with the io handler) and starts the consumer threads; the REST, A2A and
MCP side lives in app_io_handler.py.
"""

from agentkernel.pipeline import AgentRunner
from agentkernel.secret import SecretManager
from agents import set_default_openai_key

import app_agents  # noqa: F401  registers the agents this process executes

# OPENAI_API_KEY from the environment when set, else from the Secrets the chart mounts under
# /var/run/secrets/agentkernel. The value is handed to the SDK in memory; it is never written back to os.environ.
set_default_openai_key(SecretManager.current().get("OPENAI_API_KEY"))


def main():
    AgentRunner.run()


if __name__ == "__main__":
    main()
