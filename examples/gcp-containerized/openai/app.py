from agentkernel.api import RESTAPI, AgentRESTRequestHandler
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


# Adding a custom route - Option 1
@router.get("/version")
def get_app_name() -> dict[str, str]:
    return {"name": "my_custom_app", "version": "1.0.0"}


RESTAPI.add(router)


# Adding a custom route - Option 2
class CustomHandler(AgentRESTRequestHandler):
    def get_router(self) -> APIRouter:
        parent_router = super().get_router()

        @parent_router.get("/whoami")
        def whoami() -> dict[str, str]:
            return {"whoami": "I am a custom application built with Agent Kernel!"}

        return parent_router


OpenAIModule([triage_agent, math_agent, history_agent])


def main() -> None:
    RESTAPI.run([CustomHandler()])
