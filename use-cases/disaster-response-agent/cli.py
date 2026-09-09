"""Run the Disaster Response & Resource Coordination Agent locally via the Agent Kernel CLI.

Note: demo.py is the canonical entry point name used by Agent Kernel's other use-case
examples. This file is kept as an identical alias - use whichever you prefer.

Usage:
    python cli.py

Try:
    Need drinking water in Galle
    We have 50 food packs available in Colombo
    Elderly couple needs medicine urgently in Matara
    What's the status in Galle?
"""

from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule

from agent import AGENTS

OpenAIModule(AGENTS)

if __name__ == "__main__":
    CLI.main()
