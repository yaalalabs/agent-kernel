"""Agent Kernel sandbox queue broker over Kafka: the #503 Kafka shape.

The agent side and the sandbox worker are two processes decoupled by Kafka, the same split a
Lambda- or ECS-hosted agent uses with a cluster-side worker (here both halves run locally
against one config.yaml):

    python app.py            # the agent CLI (sandbox tasks go to the sandbox input topic)
    python app.py worker     # QueueBrokerWorker (executes in kubernetes pods; completions
                             # return over the sandbox output topic into the response store)

Infrastructure first: `docker compose up -d --wait`, the four sandbox topics, and a kind
cluster with k8s/rbac.yaml applied; the README walks through it and app_test.py automates it.
"""

import sys

from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule
from agentkernel.sandbox import QueueBrokerWorker
from agents import Agent

# The sandbox capability injects its own tool guidance into the system prompt when enabled;
# the instructions only pin the demo's operational ground rules.
ops_agent = Agent(
    name="ops",
    instructions="You are a Kubernetes operations assistant. Run every kubectl command through "
    "the sandbox as a shell command and answer only from what the command actually printed. "
    "Follow the user's output-format instructions exactly.",
)

OpenAIModule([ops_agent])

# Role dispatch: no argument runs the CLI (what the Test harness drives); "worker" runs the
# blocking sandbox broker worker.
ENTRYPOINTS = {"app": CLI.main, "worker": QueueBrokerWorker.run}


def main(argv: list[str]) -> int:
    role = argv[1] if len(argv) > 1 else "app"
    if role not in ENTRYPOINTS:
        print(f"usage: python app.py [{' | '.join(ENTRYPOINTS)}]", file=sys.stderr)
        return 2
    sys.argv = [argv[0]]  # the role is consumed here; entrypoints see a clean argv
    ENTRYPOINTS[role]()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
