"""The io process: Request Handler (REST, A2A and MCP) + Response Handler threads.

This is the entry point behind the chart's io-handler Deployment. It terminates REST, A2A and
MCP, enqueues requests to the input queue, consumes the output queue, and serves replies from
the response store. Agents run in the other process (app_agent_runner.py), but they are
registered here too: A2A cards and MCP agent tools are built from this process's registry, so
without them the A2A catalog and the MCP tool list would be empty. Both processes load the same
agents from app_agents.py. Nothing here runs a model, so no OpenAI key is set.

For the WebSocket execution mode (async) the chart adds a separate gateway Deployment
running WebSocketGateway.run(auth_validator=...); the io handler's API stays plain REST.
"""

from agentkernel.openai import OpenAIModule
from agentkernel.pipeline import IOHandler

from app_agents import history_agent, math_agent, triage_agent

OpenAIModule([triage_agent, math_agent, history_agent])


def main():
    IOHandler.run()


if __name__ == "__main__":
    main()
