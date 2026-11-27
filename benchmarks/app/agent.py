"""The benchmarked app's agent: the mock agent when ak-bench deploy passed mock delays, else a real OpenAI agent under the same name.

Importing this module registers the agent; it starts nothing. Each deployment folder's own entry files import it and
hand over to the host's entry point (Lambda handlers, ECS `AgentRunner.run` / `AWSWebsocketAPI.run`, ...).
"""

from agentkernel.core import Runtime
from mock_agent import AGENT_NAME, MockAgent, mock_delays

if mock_delays():
    Runtime.current().register(MockAgent())
else:
    from agentkernel.openai import OpenAIModule
    from agentkernel.secret import SecretManager
    from agents import Agent as OpenAIAgent
    from agents import set_default_openai_key

    # Through the secret capability, so the key can live in the host's secret store (SSM on AWS), not only the env.
    set_default_openai_key(SecretManager.current().get("OPENAI_API_KEY"))
    OpenAIModule(
        [
            OpenAIAgent(
                name=AGENT_NAME,
                # The reply must carry the request id from the prompt, so the agent repeats the message.
                instructions="Repeat the user's message back exactly, with nothing added or removed.",
                model="openai/gpt-4.1-mini",
            )
        ]
    )
