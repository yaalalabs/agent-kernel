"""Judge-friendly local REST entrypoint; no Meta/WhatsApp credentials required.

Run ``python rest.py`` and send Agent Kernel chat requests to ``POST /api/v1/chat``.
The same agents, state, deterministic tools, and hooks are used by the CLI and
WhatsApp entrypoints.
"""

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from agentkernel.adk import GoogleADKModule
from agentkernel.api import RESTAPI

from agent import AGENTS
from hooks import register_hooks
from startup import require_gemini_config

module = GoogleADKModule(AGENTS)
register_hooks(module, AGENTS)


if __name__ == "__main__":
    require_gemini_config()
    RESTAPI.run()
