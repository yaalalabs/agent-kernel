"""Optional AWS Lambda entrypoint for the standard Agent Kernel REST API.

Registers the agent module and exposes the Agent Kernel Lambda handler behind API
Gateway when packaged with Agent Kernel's standard AWS deployment modules. The
competition build uses ``app.py`` for the WhatsApp webhook; this module exists as
a conventional REST deployment seam and contains no Meta-specific behavior.
"""

# Local invocations honour a .env; on AWS the vars come from the Lambda config.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from agentkernel.adk import GoogleADKModule
from agentkernel.aws import Lambda

from agent import AGENTS
from hooks import register_hooks

module = GoogleADKModule(AGENTS)
register_hooks(module, AGENTS)

handler = Lambda.handler
