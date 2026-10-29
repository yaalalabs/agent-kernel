import logging

from agentkernel.framework.adk import GoogleADKModule, GoogleADKToolBuilder
from agentkernel.integration.adapter import GatewayRunner
from agentkernel.integration.livekit import LiveKitEdgeGateway
from agentkernel.pipeline import IOHandler
from google.adk.agents import Agent as GoogleAgent
from google.adk.models import Gemini
from google.genai import types

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S"
)
# One line per 100 ms of microphone audio at INFO; warnings and errors still show.
logging.getLogger("ak.integration.producer").setLevel(logging.WARNING)


class _HideResumptionHandles(logging.Filter):
    """ADK logs a new Gemini session-resumption handle every few seconds; the line says nothing you act on."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "Update session resumption handle" not in record.getMessage()


for _handler in logging.getLogger().handlers:
    _handler.addFilter(_HideResumptionHandles())
_log = logging.getLogger(__name__)

MODEL = "gemini-3.1-flash-live-preview"


def voice(name: str) -> Gemini:
    return Gemini(
        model=MODEL,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=name))
        ),
    )


def find_venues(city: str) -> str:
    """Find venues in a city that can host a team offsite."""
    return (
        f"Venues in {city}: a lakeside lodge at $210 per person per night (spa, boat trips), "
        "a city-centre hotel at $140 per person per night (meeting rooms), "
        "and a countryside hostel at $75 per person per night (basic, shared rooms)."
    )


def estimate_total(people: int, nights: int, price_per_person_per_night: int) -> str:
    """Work out the total cost of a stay, adding travel and food."""
    stay = people * nights * price_per_person_per_night
    extras = people * 120 + people * nights * 45
    return f"Stay ${stay}, travel and food ${extras}, total ${stay + extras} for {people} people over {nights} nights."


budget = GoogleAgent(
    name="budget",
    model=voice("Charon"),
    description="Cautious budget controller who challenges plans and checks the cost.",
    instruction=(
        "You are Ben, a cautious budget controller, in a voice call with the person who asked for help and with your "
        "colleague Maya, the planner. Keep every turn short and spoken. When Maya hands over her pitch, work out its "
        "real total with your tool, say the number out loud, and challenge her: name one thing to cut or swap and "
        "why. Address her by name, then transfer to planner so she can answer. "
        "When she revises the plan, check the new total and either push back once more or accept. "
        "After at most three turns each, stop debating and transfer to planner so she can report to the person."
    ),
    tools=GoogleADKToolBuilder.bind([estimate_total]),
)

# The planner is the root, so it takes the person's first words. The budget controller is its sub-agent: ADK lets
# it transfer back to its parent, which is how the two keep passing the turn between them.
planner = GoogleAgent(
    name="planner",
    model=voice("Aoede"),
    description="Enthusiastic organiser who proposes ambitious plans for a team offsite.",
    instruction=(
        "You are Maya, an enthusiastic offsite planner, in a voice call with the person who asked for help and with "
        "your colleague Ben, the budget controller. Keep every turn short and spoken. When the person tells you what "
        "they want, ask for the team size, nights and city if you do not have them. Then look up venues and pitch "
        "the best experience, not the cheapest. Then transfer to budget so Ben can respond. "
        "You and Ben work the plan out between you, without waiting for the person: when Ben challenges your "
        "pitch, answer him directly in a sentence or two, revise the plan, and transfer back to budget. "
        "After at most three turns each, stop and speak to the person: give the agreed plan and total, say where you "
        "and Ben still disagree, and ask what they think. Never ask the person to settle a point you can settle with Ben."
    ),
    tools=GoogleADKToolBuilder.bind([find_venues]),
    sub_agents=[budget],
)

GoogleADKModule([planner])

gateway = LiveKitEdgeGateway(session_id="room_01", agent_name="planner")


if __name__ == "__main__":
    IOHandler.run(gateways=[GatewayRunner(gateway)])
