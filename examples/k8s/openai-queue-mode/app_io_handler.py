"""The io process: Request Handler (REST, A2A and MCP) + Response Handler threads.

This is the entry point behind the chart's io-handler Deployment. It terminates REST, A2A and
MCP, enqueues requests to the input queue, consumes the output queue, and serves replies from
the response store. Agents run in the other process (app_agent_runner.py), but they are
registered here too: A2A cards and MCP agent tools are built from this process's registry, so
without them the A2A catalog and the MCP tool list would be empty. Keep them in sync with the
runner's copies. Nothing here runs a model, so no OpenAI key is set.

For WebSocket execution modes (async/stream) the chart adds a separate gateway Deployment
running WebSocketGateway.run(auth_validator=...); the io handler's API stays plain REST.
"""

from agentkernel.openai import OpenAIModule
from agentkernel.pipeline import IOHandler
from agents import Agent

math_agent = Agent(
    name="math",
    handoff_description="Specialist agent for math questions",
    instructions="You provide help with math problems. Do not provide reasoning or step-by-step explanations. Just give the final answer. \
         If prompted for anything else, refuse to answer.",
    model="openai/gpt-4.1-mini",
)

history_agent = Agent(
    name="history",
    handoff_description="Specialist agent for historical questions",
    instructions="You provide assistance with historical queries. Explain important events and context clearly.",
    model="openai/gpt-4.1-mini",
)

triage_agent = Agent(
    name="triage",
    instructions="You determine which agent to use based on the user's question.",
    model="openai/gpt-4.1-mini",
    handoffs=[history_agent, math_agent],
)

OpenAIModule([triage_agent, math_agent, history_agent])


def main():
    IOHandler.run()


if __name__ == "__main__":
    main()
