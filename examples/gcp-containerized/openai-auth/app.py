from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agents import Agent
from fastapi import APIRouter

math_agent = Agent(
    name="math",
    handoff_description="Specialist agent for math questions",
    instructions="You provide help with math problems. Explain your reasoning at each step and include examples. \
        If prompted for anything else you refuse to answer.",
)

history_agent = Agent(
    name="history",
    handoff_description="Specialist agent for historical questions",
    instructions="You provide assistance with historical queries. Explain important events and context clearly.",
)

triage_agent = Agent(
    name="triage",
    instructions="You determine which agent to use based on the user's question.",
    handoffs=[history_agent, math_agent],
)

router = APIRouter()


@router.get("/app")
def get_app():
    return {"name": "gcp-containerized-openai-auth", "version": "1.0.0"}


@router.post("/app_info")
def post_app_info():
    return {"info": "Agent Kernel containerized example with GCP JWT authentication"}


RESTAPI.add(router)

OpenAIModule([triage_agent, math_agent, history_agent])


def main():
    RESTAPI.run()
