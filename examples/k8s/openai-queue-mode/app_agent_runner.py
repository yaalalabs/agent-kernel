"""The runner process: consumes the input queue and executes the agents.

This is the entry point behind the chart's agent-runner Deployment. It registers the agent
modules and starts the consumer threads; the REST, A2A and MCP side lives in app_io_handler.py,
which registers the same agents. Both load them from app_agents.py.
"""

from agentkernel.openai import OpenAIModule
from agentkernel.pipeline import AgentRunner
from agentkernel.secret import SecretManager
from agents import set_default_openai_key

from app_agents import history_agent, math_agent, triage_agent

# OPENAI_API_KEY from the environment when set, else from the Secrets the chart mounts under
# /var/run/secrets/agentkernel. The value is handed to the SDK in memory; it is never written back to os.environ.
set_default_openai_key(SecretManager.current().get("OPENAI_API_KEY"))

OpenAIModule([triage_agent, math_agent, history_agent])


def main():
    AgentRunner.run()


if __name__ == "__main__":
    main()
