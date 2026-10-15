import logging
import threading
import time
from typing import Any, Optional

from google.adk.agents import Agent as GoogleAgent
from google.adk.tools import ToolContext
from google.genai import types

from agentkernel import RealtimeEvent, RealtimeHook
from agentkernel.adk import GoogleADKModule, GoogleADKToolBuilder
from agentkernel.core import ToolContext as AKToolContext
from agentkernel.integration.adapter import GatewayRunner
from agentkernel.livekit import LiveKitEdgeGateway
from agentkernel.pipeline import IOHandler, RealtimeCall

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S"
)
_log = logging.getLogger(__name__)

MODEL = "gemini-3.1-flash-live-preview"
# How long the dispatch system takes to confirm a technician visit, in the background.
DISPATCH_SECONDS = 5.0
# The specialists that take the call only once the caller's account is verified.
NEEDS_ACCOUNT = {"billing", "tech_support"}


def voice(name: str) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=name))
        )
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


def book_technician(account_id: str, day: str) -> str:
    """Request a technician visit for a customer account on a given day; the dispatch system confirms it shortly."""
    # The call's session, read while the tool runs: the background job outlives the tool call.
    session_id = AKToolContext.get().session.id
    threading.Thread(target=confirm_visit, args=(session_id, account_id, day), daemon=True).start()
    return (
        f"A technician visit is requested for account {account_id} on {day}. Tell the caller the dispatch system "
        "will confirm the time in a moment, and carry on helping them."
    )


def confirm_visit(session_id: str, account_id: str, day: str) -> None:
    """The dispatch system's answer, said into the call at its next quiet moment instead of cutting anyone off."""
    time.sleep(DISPATCH_SECONDS)
    RealtimeCall(session_id).post_when_idle(
        f"[Dispatch system] The technician visit for account {account_id} on {day} is confirmed for 8am to 12pm, "
        "reference TEC-4821. Tell the caller in one short sentence.",
        key="dispatch",
    )


def require_account(tool: Any, args: dict[str, Any], tool_context: ToolContext) -> Optional[dict]:
    """A before-tool callback: billing and tech support take the call only once the caller's account is verified.

    Returning a result answers in the tool's place, so the transfer does not happen and the agent keeps the call.
    Any other tool, and a transfer once the account is verified, runs as usual (``None``).
    """
    if tool.name != "transfer_to_agent" or args.get("agent_name") not in NEEDS_ACCOUNT:
        return None
    if tool_context.state.get("account_id"):
        return None
    return {"result": "Not transferred: ask the caller for their account number and verify it with verify_account first."}


class CallLog(RealtimeHook):
    """Logs what each side of a call says, and who has it: what an application would store or show."""

    async def on_event(self, session: Any, agent: Any, event: RealtimeEvent) -> None:
        if event.type == "caller_said":
            _log.info(f"[call {event.session_id}] caller: {event.text}")
        elif event.type == "agent_said":
            _log.info(f"[call {event.session_id}] {event.agent}: {event.text}{' (interrupted)' if event.interrupted else ''}")
        elif event.type in ("agent_changed", "reconnected"):
            _log.info(f"[call {event.session_id}] {event.type}: {event.agent}")

    def name(self) -> str:
        return "call_log"


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
        "spoken. Greet the caller, ask how you can help and, if they have not given it, their account number, and "
        "verify it with verify_account before transferring them. Answer general questions yourself."
    ),
    tools=GoogleADKToolBuilder.bind([verify_account]),
    sub_agents=[billing, tech_support],
    # Realtime calls run ADK's tool callbacks too, transfer_to_agent included: this one can refuse a transfer.
    before_tool_callback=require_account,
    generate_content_config=voice("Aoede"),
)

module = GoogleADKModule([supervisor]).realtime_hook(supervisor, [CallLog()])


if __name__ == "__main__":
    gateway = LiveKitEdgeGateway(session_id="room_01", agent_name="supervisor")
    IOHandler.run(gateways=[GatewayRunner(gateway)])
