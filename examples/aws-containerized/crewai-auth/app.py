import os
from typing import Optional

import jwt
from agentkernel.api import RESTAPI, AgentRESTRequestHandler
from agentkernel.auth import AuthValidator, ValidationContext, ValidationResult
from agentkernel.crewai import CrewAIModule
from crewai import Agent
from fastapi import APIRouter

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


# Adding a custom route
# Example custom route to support application-specific endpoints.
# All custom routes are prefixed with "/custom" by default. Refer to the config documentation for more details.
@router.get("/version")
def get_app_name():
    return {"name": "my_custom_app", "version": "1.0.0"}


RESTAPI.add(router)


CrewAIModule([math_agent, history_agent])


# Defining the Custom Auth validator for auth token validation
class CustomAuthValidator(AuthValidator):
    def validate(self, token: str, context: Optional[ValidationContext] = None) -> ValidationResult:
        """Validate JWT token and return validation result."""
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            email = payload.get("email", "")
            if email == "test@test.com":
                return ValidationResult(is_valid=True)
            return ValidationResult(is_valid=False, error_msg="Invalid token")
        except jwt.DecodeError as e:
            return ValidationResult(is_valid=False, error_msg=f"Token decode error: {str(e)}")
        except Exception as e:
            return ValidationResult(is_valid=False, error_msg=f"Token validation error: {str(e)}")


# Adding Auth handlers to the REST API
RESTAPI.add_auth_handlers(auth_validators=[CustomAuthValidator()])


def main():
    RESTAPI.run()
