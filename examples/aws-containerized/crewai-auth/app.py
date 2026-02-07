import os
from typing import Optional

from agentkernel.api import RESTAPI, AgentRESTRequestHandler
from agentkernel.auth import AuthValidator, ValidationContext, ValidationResult
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
# This example, however, showcases a combination of option 1 and 2.


CrewAIModule([math_agent, history_agent])


# Defining the Custom Auth validator for auth token validation
class CustomAuthValidator(AuthValidator):
    def validate(self, token: str, context: Optional[ValidationContext] = None) -> ValidationResult:
        """Validate JWT token and return validation result."""
        print(f"Token: {token}")
        print(f"Context: {context.model_dump_json(indent=2)}")
        print(f"Environment Variable: 'SOME_OTHER_KEY': {os.getenv('SOME_OTHER_KEY')}")
        if token != "test12345":
            return ValidationResult(is_valid=False)
        return ValidationResult(is_valid=True)


# Adding Auth handlers to the REST API
RESTAPI.add_auth_handlers(auth_validators=[CustomAuthValidator()])


def main():
    RESTAPI.run([CustomHandler()])
