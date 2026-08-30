from dotenv import load_dotenv

# See the note in server.py: .env must reach os.environ for the OpenAI SDK to find its key.
load_dotenv()

from agentkernel.cli import CLI  # noqa: E402
from agentkernel.openai import OpenAIModule  # noqa: E402

from agent import AGENTS  # noqa: E402

OpenAIModule(AGENTS)


if __name__ == "__main__":
    CLI.main()
