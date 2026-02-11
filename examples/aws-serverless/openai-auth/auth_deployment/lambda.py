import os
from typing import Optional

import jwt
from agentkernel.auth import AuthValidator, ValidationContext, ValidationResult
from agentkernel.aws import APIGatewayAuthorizer


class CustomAuthTokenValidator(AuthValidator):
    def validate(self, token: str, context: Optional[ValidationContext] = None) -> ValidationResult:
        """Validate JWT token and return validation result."""
        payload = jwt.decode(token, options={"verify_signature": False})
        print("Payload", payload)
        email = payload.get("email", "")
        if email == "test@test.com":
            return ValidationResult(is_valid=True)
        return ValidationResult(is_valid=False)


handler = APIGatewayAuthorizer(validator=CustomAuthTokenValidator()).handle
