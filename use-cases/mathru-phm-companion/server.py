from dotenv import load_dotenv

# Load .env into the process environment before anything reads configuration. Agent Kernel's
# own Config reads .env natively, but only for AK_-prefixed keys and only into the settings
# model, never into os.environ. The OpenAI SDK reads OPENAI_API_KEY from os.environ directly,
# so without this call a key kept only in .env would not be picked up.
load_dotenv()

from agentkernel.api import RESTAPI  # noqa: E402
from agentkernel.openai import OpenAIModule  # noqa: E402
from agentkernel.whatsapp import AgentWhatsAppRequestHandler  # noqa: E402

from agent import AGENTS  # noqa: E402

OpenAIModule(AGENTS)


if __name__ == "__main__":
    handler = AgentWhatsAppRequestHandler()
    RESTAPI.run([handler])
