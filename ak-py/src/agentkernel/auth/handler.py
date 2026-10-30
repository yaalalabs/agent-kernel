from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class ValidationContext(BaseModel):
    path: str | None = None
    http_method: str | None = None
    headers: dict[str, Any] | None = None


class ValidationResult(BaseModel):
    is_valid: bool
    subject: str | None = "user"
    claims: dict[str, Any] | None = None
    error_msg: str | None = None


class AuthValidator(ABC):
    """Base class for token validation.
    The validate() method must be implemented by subclasses,
    There are some basic built-in cryptographic validation helpers which can be used if needed."""

    @abstractmethod
    def validate(self, token: str, context: ValidationContext | None = None) -> ValidationResult:
        """Main validation entry point. This is where the custom logic has to be written.
        :param token: The authentication token to validate
        :param context: Optional validation context containing request metadata
        :return: ValidationResult indicating if token is valid and associated claims
        """
        pass

    def _validate_hmac(self, message: bytes, signature: str, secret: str, algorithm: str = "sha256") -> bool:
        """Basic HMAC signature validation.
        :param message: The message bytes to verify
        :param signature: The HMAC signature to validate against
        :param secret: The secret key used for HMAC generation
        :param algorithm: Hash algorithm to use (default: sha256)
        :return: True if signature is valid, False otherwise
        """
        import base64
        import hashlib
        import hmac

        mac = hmac.new(key=secret.encode(), msg=message, digestmod=getattr(hashlib, algorithm))
        expected = base64.b64encode(mac.digest()).decode()
        return hmac.compare_digest(expected, signature)

    def _validate_rs256_jwt(
        self, token: str, public_key: str, audience: str | None = None, issuer: str | None = None, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Basic RS256 JWT validation.
        :param token: The JWT token to validate
        :param public_key: The RSA public key for signature verification
        :param audience: Optional expected audience claim
        :param issuer: Optional expected issuer claim
        :param options: Additional JWT validation options
        :return: Decoded JWT claims dictionary
        :raises: jwt exceptions if token is invalid
        """
        import jwt

        return jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
            options=options or {},
        )
