import logging

from google.adk.agents import Agent as GoogleAgent
from google.genai import types

from agentkernel.framework.adk import GoogleADKModule, GoogleADKToolBuilder
from agentkernel.integration.adapter import GatewayRunner
from agentkernel.integration.livekit import LiveKitEdgeGateway
from agentkernel.pipeline import IOHandler

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S"
)
_log = logging.getLogger(__name__)

MODEL = "gemini-3.1-flash-live-preview"


def voice(name: str) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=name))
        )
    )


def get_latest_invoice(account_id: str) -> str:
    """Get the latest invoice for a customer account."""
    return (
        f"Account {account_id}: the October invoice is $64.90, due on the 28th. "
        "It includes the $49.90 monthly plan and a one-off $15 router replacement fee."
    )


def check_outage(postcode: str) -> str:
    """Check whether there is a known network outage in a postcode area."""
    if postcode.strip().upper().startswith("SW1"):
        return f"There is a known fibre outage in {postcode}. Engineers are on site; service is expected back by 6pm today."
    return f"There are no known outages in {postcode}."


def book_technician(account_id: str, day: str) -> str:
    """Book a technician visit for a customer account on a given day."""
    return f"A technician is booked for account {account_id} on {day}, between 8am and 12pm. The reference is TEC-4821."


billing = GoogleAgent(
    name="billing",
    model=MODEL,
    description="Handles invoices, charges, payments and refunds.",
    instruction=(
        "You are Acme Internet's billing specialist, taking over a call from the front desk. Introduce yourself in a few "
        "words and answer the caller's billing question straight away; the account number may already be in the "
        "conversation, so do not ask for it again. Keep answers short and spoken."
    ),
    tools=GoogleADKToolBuilder.bind([get_latest_invoice]),
    generate_content_config=voice("Charon"),
)

tech_support = GoogleAgent(
    name="tech_support",
    model=MODEL,
    description="Handles internet connection problems, outages and technician visits.",
    instruction=(
        "You are Acme Internet's technical support specialist, taking over a call from the front desk. Introduce "
        "yourself in a few words and help with the connection problem straight away, using what the caller has already "
        "said. Check for an outage before suggesting a technician visit. Keep answers short and spoken."
    ),
    tools=GoogleADKToolBuilder.bind([check_outage, book_technician]),
    generate_content_config=voice("Puck"),
)

supervisor = GoogleAgent(
    name="supervisor",
    model=MODEL,
    description="Greets callers, answers general questions and routes them to the right team.",
    instruction=(
        "You are the front desk of Acme Internet's support line, speaking with a caller. Keep every answer short and "
        "spoken. Greet the caller, ask how you can help and, if they have not given it, their account number. "
        "Answer general questions yourself."
    ),
    sub_agents=[billing, tech_support],
    generate_content_config=voice("Aoede"),
)

GoogleADKModule([supervisor])

gateway = LiveKitEdgeGateway(session_id="room_01", agent_name="supervisor")


if __name__ == "__main__":
    IOHandler.run(gateways=[GatewayRunner(gateway)])
