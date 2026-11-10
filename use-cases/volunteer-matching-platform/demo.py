from agentkernel.cli import CLI
from agentkernel.pydanticai import PydanticAIModule

from agent import AGENTS

PydanticAIModule(AGENTS)


if __name__ == "__main__":
    CLI.main()
