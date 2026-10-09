import logging

from agents import Agent as OpenAIAgent

from agentkernel.framework.openai import OpenAIModule, OpenAIToolBuilder
from agentkernel.integration.adapter import GatewayRunner
from agentkernel.integration.livekit import LiveKitEdgeGateway
from agentkernel.pipeline import IOHandler

logging.basicConfig(level=logging.INFO)
_log = logging.getLogger(__name__)

MODEL = "gpt-realtime"


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


supervisor = OpenAIAgent(
    name="supervisor",
    model=MODEL,
    handoff_description="Greets callers, answers general questions and routes them to the right team.",
    instructions=(
        "You are the front desk of Acme Internet's support line, speaking with a caller. Keep every answer short and spoken. "
        "Greet the caller, ask how you can help and, if they have not given it, their account number. "
        "Hand billing questions (invoices, charges, payments, refunds) to the billing agent, and connection problems "
        "(slow or no internet, outages, technician visits) to the tech_support agent. Before handing off, tell the caller "
        "in one short sentence that you are connecting them. Answer anything else yourself."
    ),
)

billing = OpenAIAgent(
    name="billing",
    model=MODEL,
    handoff_description="Invoices, charges, payments and refunds.",
    instructions=(
        "You are Acme Internet's billing specialist, taking over a call from the front desk. Introduce yourself in a few "
        "words and answer the caller's billing question straight away; the account number may already be in the "
        "conversation, so do not ask for it again. Keep answers short and spoken. If the caller asks about anything "
        "other than billing, hand the call back to the supervisor."
    ),
    tools=OpenAIToolBuilder.bind([get_latest_invoice]),
    handoffs=[supervisor],
)

tech_support = OpenAIAgent(
    name="tech_support",
    model=MODEL,
    handoff_description="Internet connection problems, outages and technician visits.",
    instructions=(
        "You are Acme Internet's technical support specialist, taking over a call from the front desk. Introduce "
        "yourself in a few words and help with the connection problem straight away, using what the caller has already "
        "said. Check for an outage before suggesting a technician visit. Keep answers short and spoken. If the caller "
        "asks about anything other than their connection, hand the call back to the supervisor."
    ),
    tools=OpenAIToolBuilder.bind([check_outage, book_technician]),
    handoffs=[supervisor],
)

supervisor.handoffs = [billing, tech_support]

OpenAIModule([supervisor])

gateway = LiveKitEdgeGateway(session_id="room_01", agent_name="supervisor")


if __name__ == "__main__":
    IOHandler.run(gateways=[GatewayRunner(gateway)])
