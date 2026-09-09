import os
import logging
import litellm
#litellm._turn_on_debug()

os.environ["ADK_SUPPRESS_GEMINI_LITELLM_WARNINGS"] = "true"

from agentkernel.adk import GoogleADKModule, GoogleADKToolBuilder
from agentkernel.cli import CLI
from agentkernel.core import ToolContext
from google.adk.agents import Agent, LlmAgent
from google.adk.models.lite_llm import LiteLlm

# Initialize natively
gemini_model = LiteLlm(model="gemini/gemini-3.6-flash")

def get_system_status(sensor_id: str) -> str:
    """Returns the current temperature and hardware status for a given sensor via LoRa telemetry bridge."""
    logger = logging.getLogger(__name__)
    logger.debug("Session ID: %s", ToolContext.get().session.id)

    if sensor_id == "CoolingTower1":
        return "Current temperature is 38°C (Threshold breached: >35°C). Fan speed at 100%. High energy waste detected."
    else:
        return f"Cannot find telemetry for {sensor_id}."

intake_agent = Agent(
    name="intake",
    model=gemini_model,
    description="Fetches real-time telemetry data from the cooling tower",
    instruction="""
    You are the Intake Agent. Use the get_system_status tool to get the current temperature of 'CoolingTower1'. Give short, direct answers.
    """,
    tools=GoogleADKToolBuilder.bind([get_system_status]),
)

analysis_agent = Agent(
    name="analysis",
    model=gemini_model,
    description="Analyzes cooling data for energy waste",
    instruction="""
    You are the Analysis Agent. You evaluate temperature data.
    If it is above 35°C, warn the user that they are wasting energy and risking hardware damage.
    Recommend lowering the threshold.
    """,
)

triage_agent = LlmAgent(
    name="triage",
    model=gemini_model,
    description="Routes the user to the appropriate specialist agent.",
    instruction="""
    You determine which agent to use based on the user's question.
    If the user asks to get or check the data/status, transfer to the agent named "intake".
    If the user asks to analyze the data, transfer to the agent named "analysis".
    """,
    sub_agents=[intake_agent, analysis_agent],
)

GoogleADKModule([triage_agent, intake_agent, analysis_agent])

if __name__ == "__main__":
    CLI.main()