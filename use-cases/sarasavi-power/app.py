"""Local / container entrypoint — serves the WhatsApp webhook over REST.

This is the documented Agent Kernel WhatsApp run path. Judges without a Meta
number should use ``demo.py`` or ``rest.py`` instead. This module registers the
agents and then runs the dedicated WhatsApp webhook handler.

Run:  python app.py     (after setting AK_WHATSAPP__* env vars — see README)
Webhook is served at  /whatsapp/webhook  (verification challenge handled by AK).
"""

# Load .env (if present) before anything reads os.environ (e.g. the model name).
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import logging

from agentkernel.adk import GoogleADKModule
from agentkernel.api import RESTAPI

# Agent Kernel configures only its own "ak" logger (and optionally root), so the
# use-case's own loggers would otherwise be invisible — which hides voice-call
# diagnostics entirely. Give "sarasavi.*" its own stream handler at INFO.
_sarasavi_log = logging.getLogger("sarasavi")
if not _sarasavi_log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    _sarasavi_log.addHandler(_handler)
_sarasavi_log.setLevel(logging.INFO)
_sarasavi_log.propagate = False

from agent import AGENTS
from hooks import register_hooks
from startup import require_gemini_config, require_whatsapp_config
from whatsapp_ext import SarasaviWhatsAppHandler

# Register the multi-agent module with the Agent Kernel runtime, then attach the
# deterministic guardrail hooks (safety pre-hook + disclaimer post-hook).
module = GoogleADKModule(AGENTS)
register_hooks(module, AGENTS)

if __name__ == "__main__":
    require_gemini_config()
    require_whatsapp_config()
    handler = SarasaviWhatsAppHandler()
    RESTAPI.run([handler])
