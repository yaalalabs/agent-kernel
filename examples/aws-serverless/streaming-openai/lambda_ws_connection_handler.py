import jwt
from agentkernel.auth import AuthValidator, ValidationResult
from agentkernel.aws import WebsocketConnectionHandler


class CustomAuthTokenValidator(AuthValidator):
    def validate(self, token: str) -> ValidationResult:
        """Validate JWT token and return validation result."""
        try:
            # WARNING: Signature verification is disabled here for documentation purposes only.
            # This makes the example auth trivially forgeable; use real JWT verification in production.
            payload = jwt.decode(token, options={"verify_signature": False})
            email = payload.get("email", "")
            user_id = payload.get("userId", "")
            if user_id in ["user-1", "user-2"] and email in ["test1@test.com", "test2@test.com"]:
                return ValidationResult(is_valid=True, claims={"userId": user_id})
            return ValidationResult(is_valid=False, error_msg="Invalid user ID or email in token")
        except Exception as e:
            return ValidationResult(is_valid=False, error_msg=f"Token validation failed: {str(e)}")


handler = WebsocketConnectionHandler.set_auth_validator(CustomAuthTokenValidator()).handler
