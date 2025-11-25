from agentkernel.api import RESTAPI, AgentRESTRequestHandler
from agentkernel.crewai import CrewAIModule
from fastapi import APIRouter

from crewai import Agent

math_agent = Agent(
    role="math",
    goal="Specialist agent for math questions",
    backstory="You provide help with math problems. Explain your reasoning at each step and include examples. \
        If prompted for anything else you refuse to answer.",
    verbose=False,
)

history_agent = Agent(
    role="history",
    goal="Specialist agent for historical questions",
    backstory="You provide assistance with historical queries. Explain important events and context clearly.",
    verbose=False,
)

router = APIRouter()


# Adding a custom route - Option 1
# Example custom route to support application-specific endpoints.
# All custom routes are prefixed with "/custom" by default. Refer to the config documentation for more details.
@router.get("/version")
def get_app_name():
    return {"name": "my_custom_app", "version": "1.0.0"}


RESTAPI.add(router)


# Adding a custom route - Option 2
# Override the default handler and add your own custom logic.
class CustomHandler(AgentRESTRequestHandler):
    def get_router(self) -> APIRouter:
        parent_router = super().get_router()

        @parent_router.get("/whoami")
        def whoami():
            return {"whoami": "I am a custom application built with Agent Kernel!"}

        return parent_router


# Adding custom routes - Option 3
# Create your own Router inheriting from RESTRequestHandler. In this case you'll have to
# map agent invocation endpoints by yourself.
# This example, however, shows cases a combination of option 1 and 2.


CrewAIModule([math_agent, history_agent])


def main():
    RESTAPI.run([CustomHandler()])
