from typing import Optional

from agentkernel.api import AuthValidator, ValidationContext, ValidationResult
from agentkernel.aws import APIGatewayAuthorizer


class CustomAuthTokenValidator(AuthValidator):
    def validate(self, token: str, context: Optional[ValidationContext] = None) -> ValidationResult:
        """Validate JWT token and return validation result."""

        print(f"Token: {token}")
        print(f"Context: {context.model_dump_json(indent=2)}")

        if token != "test12345":
            return ValidationResult(is_valid=False)

        return ValidationResult(is_valid=True)


handler = APIGatewayAuthorizer(validator=CustomAuthTokenValidator()).handle