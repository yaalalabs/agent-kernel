from typing import Optional

import jwt
from agentkernel.auth import AuthValidator, ValidationContext, ValidationResult
from agentkernel.aws import ECSIOHandler


# Validates the `?token=` query string on the WebSocket $connect handshake
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
                # 'userId' claim keys the connection for output-queue routing
                return ValidationResult(is_valid=True, claims={"userId": user_id})
            return ValidationResult(is_valid=False, error_msg="Invalid user ID or email in token")
        except Exception as e:
            return ValidationResult(is_valid=False, error_msg=f"Token validation failed: {str(e)}")


def main():
    ECSIOHandler.run(auth_validator=CustomAuthValidator())


if __name__ == "__main__":
    main()
