import asyncio
import logging
from typing import Any, Optional

from agentkernel import RealtimeEvent, RealtimeObserver
from agentkernel.adk import GoogleADKModule, GoogleADKToolBuilder
from agentkernel.integration.adapter import GatewayRunner
from agentkernel.livekit import LiveKitEdgeGateway
from agentkernel.pipeline import IOHandler, RealtimeCall
from google.adk.agents import Agent as GoogleAgent
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.genai import types

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S"
)
_log = logging.getLogger(__name__)

MODEL = "gemini-3.1-flash-live-preview"
# How long the dispatch system takes to confirm a technician visit; the tool waits for it.
DISPATCH_SECONDS = 5.0
# The specialists that take the call only once the caller's account is verified.
NEEDS_ACCOUNT = {"billing", "tech_support"}


def voice(name: str) -> Gemini:
    """The Live model speaking in a Gemini prebuilt voice: ADK's live run takes each agent's voice from its model."""
    return Gemini(
        model=MODEL,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=name))
        ),
    )


def verify_account(account_id: str, tool_context: ToolContext) -> str:
    """Verify a caller's account number before helping them with it."""
    account_id = account_id.strip().upper()
    if not account_id.startswith("A-"):
        return f"There is no account {account_id}. Account numbers look like A-1042: ask the caller again."
    # The ADK tool state lasts for the whole call, across transfers, so every agent sees the verified account.
    tool_context.state["account_id"] = account_id
    return f"Account {account_id} is verified: Jane Doe, fibre 500 plan."


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


class Dispatch:
    """The dispatch system: it confirms a technician visit a few seconds after it is asked, one booking per account
    at a time."""

    def __init__(self) -> None:
        # The accounts whose visit the dispatch system is confirming now.
        self.booking: set[str] = set()

    async def book(self, account_id: str, day: str) -> str:
        if account_id in self.booking:
            return f"A visit for account {account_id} is already being booked. Do not book again."
        self.booking.add(account_id)
        try:
            await asyncio.sleep(DISPATCH_SECONDS)  # the dispatch system's own time
        finally:
            self.booking.discard(account_id)
        return f"The technician visit for account {account_id} on {day} is confirmed for 8am to 12pm, reference TEC-4821."


dispatch = Dispatch()


async def book_technician(account_id: str, day: str) -> str:
    """Book a technician visit for a customer account on a given day; waits for the dispatch system to confirm it."""
    # The tool waits on the realtime loop, which keeps playing every call's audio meanwhile; the call is busy until it
    # answers, so nothing is posted into it and the model is not taken for stalled.
    return await dispatch.book(account_id, day)


def require_account(tool: Any, args: dict[str, Any], tool_context: ToolContext) -> Optional[dict]:
    """A before-tool callback: billing and tech support take the call only once the caller's account is verified.

    Returning a result answers in the tool's place, so the transfer does not happen and the agent keeps the call.
    Any other tool, and a transfer once the account is verified, runs as usual (``None``).
    """
    if tool.name != "transfer_to_agent" or args.get("agent_name") not in NEEDS_ACCOUNT:
        return None
    if tool_context.state.get("account_id"):
        return None
    return {
        "result": "Not transferred: ask the caller for their account number and verify it with verify_account first."
    }


class CallLog(RealtimeObserver):
    """Logs what each side of a call says, and who has it: what an application would store or show."""

    async def on_event(self, session: Any, agent: Any, event: RealtimeEvent) -> None:
        if event.type == "caller_said":
            _log.info(f"[call {event.session_id}] caller: {event.text}")
        elif event.type == "agent_said":
            _log.info(
                f"[call {event.session_id}] {event.agent}: {event.text}{' (interrupted)' if event.interrupted else ''}"
            )
        elif event.type in ("agent_changed", "reconnected"):
            _log.info(f"[call {event.session_id}] {event.type}: {event.agent}")

    def name(self) -> str:
        return "call_log"


billing = GoogleAgent(
    name="billing",
    model=voice("Charon"),
    description="Handles invoices, charges, payments and refunds.",
    instruction=(
        "You are Acme Internet's billing specialist, taking over a call from the front desk. Introduce yourself in a few "
        "words and answer the caller's billing question straight away; the account number may already be in the "
        "conversation, so do not ask for it again. Keep answers short and spoken."
    ),
    tools=GoogleADKToolBuilder.bind([get_latest_invoice]),
)

tech_support = GoogleAgent(
    name="tech_support",
    model=voice("Puck"),
    description="Handles internet connection problems, outages and technician visits.",
    instruction=(
        "You are Acme Internet's technical support specialist, taking over a call from the front desk. Introduce "
        "yourself in a few words and help with the connection problem straight away, using what the caller has already "
        "said. Check for an outage before suggesting a technician visit. Keep answers short and spoken."
    ),
    tools=GoogleADKToolBuilder.bind([check_outage, book_technician]),
)

supervisor = GoogleAgent(
    name="supervisor",
    model=voice("Aoede"),
    description="Greets callers, answers general questions and routes them to the right team.",
    instruction=(
        "You are the front desk of Acme Internet's support line, speaking with a caller. Keep every answer short and "
        "spoken. Greet the caller, ask how you can help and, if they have not given it, their account number, and "
        "verify it with verify_account before transferring them. Answer general questions yourself."
    ),
    tools=GoogleADKToolBuilder.bind([verify_account]),
    sub_agents=[billing, tech_support],
    # Realtime calls run ADK's tool callbacks too, transfer_to_agent included: this one can refuse a transfer.
    before_tool_callback=require_account,
)

module = GoogleADKModule([supervisor])


if __name__ == "__main__":
    RealtimeCall.observe(CallLog())
    gateway = LiveKitEdgeGateway(session_id="room_01", agent_name="supervisor")
    IOHandler.run(gateways=[GatewayRunner(gateway)])
