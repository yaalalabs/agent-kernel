from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule

from agent import AGENTS

OpenAIModule(AGENTS)


if __name__ == "__main__":
    CLI.main()
