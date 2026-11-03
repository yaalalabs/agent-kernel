"""Agent runner for the two-process topology (README: "Two ways to run it").

Not needed for the default single-process run, where `app.py` hosts the runner as a thread. On a
broker transport the runner is its own process: it drains the input queue, executes the agent, and
sends each event to the output queue. It imports `app` for the side effect of defining the agent —
the runner needs the same registry the API has, and nothing else from it.
"""

from agentkernel.pipeline import AgentRunner

import app  # noqa: F401  — registers the planner agent with the Runtime

if __name__ == "__main__":
    AgentRunner.run()
