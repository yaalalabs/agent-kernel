import jwt
from agentkernel.aws import WebsocketConnectionHandler
from agentkernel.auth import AuthValidator, ValidationResult


class CustomAuthTokenValidator(AuthValidator):
    def validate(self, token: str) -> ValidationResult:
        """Validate JWT token and return validation result."""
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            email = payload.get("email", "")
            user_id = payload.get("userId", "")
            if user_id == "user-1" and email == "test@test.com":
                return ValidationResult(is_valid=True, claims={"userId": user_id})
            return ValidationResult(is_valid=False, error_msg="Invalid user ID or email in token")
        except Exception as e:
            return ValidationResult(is_valid=False, error_msg=f"Token validation failed: {str(e)}")

handler = WebsocketConnectionHandler.set_auth_validator(CustomAuthTokenValidator()).handler