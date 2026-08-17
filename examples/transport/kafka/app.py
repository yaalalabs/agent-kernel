"""Agent Kernel queue mode over Kafka: the two-process pipeline.

Kafka is a broker transport, so the pipeline is split across two processes that share the queues
and the response store:

    python app.py io        # Request Handler (REST API) + Response Handler
    python app.py runner    # Agent Runner

Both read the same config.yaml. Start the infrastructure first with ``python kafka_tester.py up``.
"""

import sys

from agentkernel.openai import OpenAIModule
from agentkernel.pipeline import AgentRunner, IOHandler
from agents import Agent

from tool import fetch_customer_activity

general_agent = Agent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and direct answers.",
)

customer_support_agent = Agent(
    name="support",
    instructions="You are a customer feedback agent. When I give you the name of the customer you will generate "
    "the feedback conversation. I will also tell the banking operation this customer carried out. "
    "You will only ask questions on satisfaction based on only the activities the user carried out. "
    "When I provide the name and the work, you will assume you are having a conversation with this "
    "customer itself and mimic the conversation. Ask questions one by one and gather answers and show "
    "the summary once the conversation is over.",
    tools=[fetch_customer_activity],
)

triage_agent = Agent(
    name="triage",
    instructions="You determine which agent to use based on the user's question.",
    handoffs=[general_agent, customer_support_agent],
)

OpenAIModule([triage_agent, general_agent, customer_support_agent])

# The two process entrypoints. RESTAPI.run() is deliberately not used here: it only boots the
# whole pipeline in-process when the transport resolves to in_memory, so on a broker transport the
# IO side is started explicitly through IOHandler.
ENTRYPOINTS = {"io": IOHandler.run, "runner": AgentRunner.run}


def main(argv: list[str]) -> int:
    role = argv[1] if len(argv) > 1 else ""
    if role not in ENTRYPOINTS:
        print(f"usage: python app.py [{' | '.join(ENTRYPOINTS)}]", file=sys.stderr)
        return 2
    ENTRYPOINTS[role]()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
