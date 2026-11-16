"""Agent Kernel queue mode on Cloud Run: one image, two services.

    main()    the edge: the REST API and the response handler (CloudRun.run())
    runner()  the agent runner: Pub/Sub pushes each request to it (CloudRunAgentRunner.run())

Terraform deploys the edge with the image's CMD, which calls main(), and the agent runner with
agent_runner.command, which calls runner(). Both load the same agents: the runner runs them, and
the edge lists them.
"""

from agentkernel.gcp import CloudRun, CloudRunAgentRunner
from agentkernel.openai import OpenAIModule
from agents import Agent

math_agent = Agent(
    name="math",
    handoff_description="Specialist agent for math questions",
    instructions="You provide help with math problems. Explain your reasoning at each step and include examples. \
        If prompted for anything else you refuse to answer.",
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
    handoffs=[history_agent, math_agent],
    model="openai/gpt-4.1-mini",
)

OpenAIModule([triage_agent, math_agent, history_agent])


def main() -> None:
    """The edge: takes chat requests, publishes them to Pub/Sub, and answers with the reply."""
    CloudRun.run()


def runner() -> None:
    """The agent runner: serves the requests Pub/Sub pushes and publishes each reply."""
    CloudRunAgentRunner.run()
