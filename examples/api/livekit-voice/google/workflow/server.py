import logging

from agentkernel.framework.adk import GoogleADKModule, GoogleADKToolBuilder
from agentkernel.integration.adapter import GatewayRunner
from agentkernel.integration.livekit import LiveKitEdgeGateway
from agentkernel.pipeline import IOHandler
from google.adk.agents import Agent as GoogleAgent
from google.adk.models import Gemini
from google.adk.workflow import Workflow
from google.genai import types

MODEL = "gemini-3.1-flash-live-preview"


def voice(name: str) -> Gemini:
    return Gemini(
        model=MODEL,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=name))
        ),
    )


def find_slots(day: str) -> str:
    """Find the free appointment slots on a day."""
    return f"Free slots on {day}: 09:30, 11:00 and 15:45."


def book_appointment(name: str, reason: str, slot: str) -> str:
    """Book the appointment and return its reference."""
    return f"Booked: {name}, {reason}, {slot}. Reference CL-4821."


# A speaking node of a workflow declares mode='task' (or 'chat'). A node left without a mode runs outside the live
# connection, so the caller would hear nothing from it. A task node talks to the caller until it has what it needs,
# then calls ADK's own finish_task tool; the workflow's edge then starts the next node.
intake = GoogleAgent(
    name="intake",
    model=voice("Aoede"),
    mode="task",
    description="Greets the caller and finds out who they are and why they are calling.",
    instruction=(
        "You are Ana, the intake assistant of a small clinic, in a voice call with a caller who wants an appointment. "
        "Keep every turn short and spoken. Greet the caller, then ask for their name and the reason for the visit, "
        "one question at a time. When you have both, call finish_task with the name and the reason in one sentence."
    ),
)

scheduler = GoogleAgent(
    name="scheduler",
    model=voice("Charon"),
    mode="task",
    description="Offers free slots and agrees one with the caller.",
    instruction=(
        "You are Ben, the clinic scheduler, in the same voice call. You have the caller's name and reason from the "
        "intake step. Keep every turn short and spoken. Ask which day suits them, look up the free slots with your "
        "tool, read them out, and let the caller pick one. When they have picked a slot, call finish_task with the "
        "name, the reason and the chosen day and time in one sentence."
    ),
    tools=GoogleADKToolBuilder.bind([find_slots]),
)

confirmer = GoogleAgent(
    name="confirmer",
    model=voice("Kore"),
    mode="task",
    description="Books the appointment and confirms it to the caller.",
    instruction=(
        "You are Kim, the clinic's confirmation desk, in the same voice call. You have the caller's name, reason, "
        "day and time from the earlier steps. Keep every turn short and spoken. Book the appointment with your "
        "tool, read the reference out loud, thank the caller and say goodbye. Then call finish_task."
    ),
    tools=GoogleADKToolBuilder.bind([book_appointment]),
)

# The workflow is the root. It is a container, not a voice: the edges fix the order, so the caller always goes
# intake -> scheduler -> confirmer. Only the workflow is registered with Agent Kernel.
booking_flow = Workflow(
    name="booking_flow",
    edges=[("START", intake), (intake, scheduler), (scheduler, confirmer)],
)

GoogleADKModule([booking_flow])

gateway = LiveKitEdgeGateway(session_id="room_01", agent_name="booking_flow")


if __name__ == "__main__":
    IOHandler.run(gateways=[GatewayRunner(gateway)])
