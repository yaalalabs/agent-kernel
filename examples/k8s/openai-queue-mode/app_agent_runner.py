"""The runner process: consumes the input queue and executes the agents.

This is the entry point behind the chart's agent-runner Deployment. It registers the agent
modules and starts the consumer threads; the REST side lives in app_io_handler.py.
"""

from agentkernel.openai import OpenAIModule
from agentkernel.pipeline import AgentRunner
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
    AgentRunner.run()


if __name__ == "__main__":
    main()
