from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agents import Agent

from identity import IdentitySeedPreHook

# The agent knows nothing about identity — the sandbox capability (enabled in config.yaml)
# injects the tool guidance, and the IdentitySeedPreHook below authenticates each request and
# records who the caller is. Sandboxed code then runs under that user's identity.
coder_agent = Agent(
    name="coder",
    instructions=(
        "You are a coding assistant with access to an execution sandbox. Prefer running real code, "
        "and report the sandbox's actual output verbatim."
    ),
)

# IdentitySeedPreHook runs before the agent (custom pre-hooks precede system pre-hooks), so the
# caller's identity is on the session before any sandbox tool call resolves the principal.
OpenAIModule([coder_agent]).pre_hook(coder_agent, [IdentitySeedPreHook()])

if __name__ == "__main__":
    RESTAPI.run()
