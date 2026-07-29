from typing import Optional

import jwt
from agentkernel.auth import AuthValidator, ValidationContext, ValidationResult
from agentkernel.aws import AWSWebsocketAPI
from agentkernel.openai import OpenAIModule
from agents import Agent

math_agent = Agent(
    name="math",
    handoff_description="Specialist agent for math questions",
    instructions="You provide help with math problems. Do not provide reasoning or step-by-step explanations. Just give the final answer. \
         If prompted for anything else, refuse to answer.",
    model="openai/gpt-4.1-mini",
)

history_agent = Agent(
    name="history",
    handoff_description="Specialist agent for historical questions",
    instructions="You provide assistance with historical queries. Explain important events and context clearly.",
    model="openai/gpt-4.1-mini",
)

triage_agent = Agent(
    name="triage",
    instructions="You determine which agent to use based on the user's question.",
    model="openai/gpt-4.1-mini",
    handoffs=[history_agent, math_agent],
)

OpenAIModule([triage_agent, math_agent, history_agent])


# Auth validator for the WebSocket $connect handshake. The client passes a token via the
# `?token=` query string; a rejected (non is_valid) result closes the connection before it opens.
class CustomAuthValidator(AuthValidator):
    def validate(self, token: str, context: Optional[ValidationContext] = None) -> ValidationResult:
        """Validate JWT token and return validation result.

        WARNING: Signature verification is disabled here for demo purposes only.
        This makes the example auth trivially forgeable; use real JWT verification in production.
        """
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            user_id = payload.get("userId", "")
            email = payload.get("email", "")
            if user_id in ["user-1", "user-2"] and email in ["test1@test.com", "test2@test.com"]:
                # 'userId' is required in claims — the framework uses it to key the
                # WebSocket connection so replies can be pushed back to the right client.
                return ValidationResult(is_valid=True, claims={"userId": user_id})
            return ValidationResult(is_valid=False, error_msg="Invalid user ID or email in token")
        except Exception as e:
            return ValidationResult(is_valid=False, error_msg=f"Token validation failed: {str(e)}")

@AWSWebsocketAPI.register("status")  # Terraform: ws_routes = [{ route = "status" }]
async def status(ctx: dict) -> dict:
    return {"status": "OK", "user_id": ctx["user_id"]}


@AWSWebsocketAPI.register("echo")  # Terraform: ws_routes = [{ route = "echo" }]
async def echo(ctx: dict) -> dict:
    return ctx


def main():
    AWSWebsocketAPI.set_auth_handler(auth_validator=CustomAuthValidator()).run()


if __name__ == "__main__":
    main()
