"""The WebSocket gateway process: owns client sockets and nothing else.

This is the entry point behind the chart's ws-gateway Deployment (async/stream execution
modes). It authenticates each /ws handshake with the validator below, enqueues chat frames
directly to the transport, and receives reply pushes from the Response Handler on
/internal/push; agents run in app_agent_runner.py and REST stays on app_io_handler.py.
"""

from typing import Optional

import jwt
from agentkernel.auth import AuthValidator, ValidationContext, ValidationResult
from agentkernel.pipeline import WebSocketGateway


class CustomAuthValidator(AuthValidator):
    """Validates the ``?token=`` query string on the WebSocket handshake."""

    def validate(self, token: str, context: Optional[ValidationContext] = None) -> ValidationResult:
        """Validate a JWT token and return the claims keying the connection.

        WARNING: Signature verification is disabled here for demo purposes only.
        This makes the example auth trivially forgeable; use real JWT verification in production.
        """
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            user_id = payload.get("userId", "")
            email = payload.get("email", "")
            if user_id in ["user-1", "user-2"] and email in ["test1@test.com", "test2@test.com"]:
                # The 'userId' claim keys the connection for reply delivery
                return ValidationResult(is_valid=True, claims={"userId": user_id})
            return ValidationResult(is_valid=False, error_msg="Invalid user ID or email in token")
        except Exception as e:
            return ValidationResult(is_valid=False, error_msg=f"Token validation failed: {str(e)}")


def main():
    WebSocketGateway.run(auth_validator=CustomAuthValidator())


if __name__ == "__main__":
    main()
