"""The agent runner Container App: consumes the Service Bus input queue and runs the agents.

The Terraform module starts it with agent_runner_command (python app_agent_runner.py) in the same
image as the edge, and scales it on the input queue's length. OPENAI_API_KEY comes from the
environment the module injects into both apps.
"""

from agentkernel.openai import OpenAIModule
from agentkernel.pipeline import AgentRunner

from app_agents import history_agent, math_agent, triage_agent

OpenAIModule([triage_agent, math_agent, history_agent])


def main():
    AgentRunner.run()


if __name__ == "__main__":
    main()
