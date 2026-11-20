import logging

from agentkernel.framework.openai import OpenAIModule, OpenAIToolBuilder
from agentkernel.integration.adapter import EdgeLifecycleRESTRequestHandler
from agentkernel.integration.livekit import LiveKitLifecycleAdapter
from agentkernel.pipeline import IOHandler
from agents.realtime import RealtimeAgent

from voice_guardrails import TypedChatPIIRedactor, VoiceOutputGuardrail

logging.basicConfig(level=logging.INFO)


def lookup_customer(name: str) -> str:
    """Look up a customer's contact details by name."""
    return f"{name}: email {name.lower()}@example.com, phone +94 77 123 4567, card on file 4111 1111 1111 1111."


support_agent = RealtimeAgent(
    name="support",
    handoff_description="Bank support agent",
    instructions=(
        "You are a bank support agent. Give short and direct answers. "
        "Use lookup_customer when asked for a customer's details and read them out."
    ),
    tools=OpenAIToolBuilder.bind([lookup_customer]),
)

(
    OpenAIModule([support_agent])
    .run_options(
        support_agent, model_config={"initial_model_settings": {"model_name": "gpt-realtime", "voice": "alloy"}}
    )
    .pre_hook(support_agent, [TypedChatPIIRedactor()])
    .post_hook(support_agent, [VoiceOutputGuardrail()])
)


if __name__ == "__main__":
    IOHandler.run(handlers=[EdgeLifecycleRESTRequestHandler(LiveKitLifecycleAdapter())])
