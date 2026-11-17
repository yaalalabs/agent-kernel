"""The edge Container App: REST behind APIM, plus the Service Bus output-queue consumer.

It enqueues each chat request on the input queue, consumes replies from the output queue into the
Redis response store, and answers the waiting REST call from there. Agents run in the agent runner
app (app_agent_runner.py); they are registered here only so this process knows their names.
"""

from agentkernel.openai import OpenAIModule
from agentkernel.pipeline import IOHandler

from app_agents import history_agent, math_agent, triage_agent

OpenAIModule([triage_agent, math_agent, history_agent])


def main():
    IOHandler.run()


if __name__ == "__main__":
    main()
