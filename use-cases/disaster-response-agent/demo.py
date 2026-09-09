"""Run the Disaster Response & Resource Coordination Agent locally via the Agent Kernel CLI.

This is the canonical local entry point, matching the naming convention used by other
Agent Kernel use-case examples (see agent-kernel/use-cases/waste-sorting-assistant/demo.py).
cli.py is kept as an alias for anyone who already has muscle memory for it.

Usage:
    python demo.py

Try:
    Need drinking water in Galle
    We have 50 food packs available in Colombo
    Elderly couple needs medicine urgently in Matara, no transport
    What's the status in Galle?
"""

from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule

from agent import AGENTS

OpenAIModule(AGENTS)

if __name__ == "__main__":
    CLI.main()
