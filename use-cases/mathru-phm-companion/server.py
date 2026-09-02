from dotenv import load_dotenv

# Load .env into the process environment before anything reads configuration. Agent Kernel's
# own Config reads .env natively, but only for AK_-prefixed keys and only into the settings
# model, never into os.environ. The OpenAI SDK reads OPENAI_API_KEY from os.environ directly,
# so without this call a key kept only in .env would not be picked up.
load_dotenv()

from agentkernel.api import RESTAPI  # noqa: E402
from agentkernel.openai import OpenAIModule  # noqa: E402
from agentkernel.whatsapp import AgentWhatsAppRequestHandler  # noqa: E402

import redaction  # noqa: E402
from agent import AGENTS, mathru_triage_agent  # noqa: E402
from hooks import BlockUnsafeLanguageHook  # noqa: E402

# Phone numbers are the session ids here, so they reach Agent Kernel's own loggers too.
redaction.install()

# The hook is registered on the ENTRY agent only. Agent Kernel runs the whole turn,
# handoffs included, inside one runner call and then applies the entry agent's post-hooks
# to the result, so this sees every agent's final text. A hook on a handoff target would
# never fire.
OpenAIModule(AGENTS).post_hook(mathru_triage_agent, [BlockUnsafeLanguageHook()])


if __name__ == "__main__":
    handler = AgentWhatsAppRequestHandler()
    RESTAPI.run([handler])
