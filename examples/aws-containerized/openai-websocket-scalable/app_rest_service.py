from typing import Optional

import jwt
from agentkernel.auth import AuthValidator, ValidationContext, ValidationResult
from agentkernel.aws import AWSWebsocketAPI, ECSIOHandler, ECSWebSocketRequestHandler


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
            if user_id and email == "test@test.com":
                # 'userId' is required in claims — the WebSocket connection is keyed by it so
                # the output-queue consumer can push replies back to the right client.
                return ValidationResult(is_valid=True, claims={"userId": user_id})
            return ValidationResult(is_valid=False, error_msg="Invalid token")
        except Exception as e:
            return ValidationResult(is_valid=False, error_msg=f"Token validation failed: {str(e)}")


@AWSWebsocketAPI.register("echo")  # Terraform: ws_routes = [{ route = "echo" }]
async def echo(ctx: dict) -> dict:
    return ctx

def main():
    ECSIOHandler.run(auth_validator=CustomAuthValidator())


if __name__ == "__main__":
    main()
