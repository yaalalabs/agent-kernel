from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from pydantic import BaseModel


class ValidationContext(BaseModel):
    path: Optional[str] = None
    http_method: Optional[str] = None
    headers: Dict[str, str]


class ValidationResult(BaseModel):
    is_valid: bool
    subject: Optional[str] = "user"
    claims: Optional[Dict[str, Any]] = None
    error_msg: Optional[str] = None


class AuthValidator(ABC):
    """Base class for token validation.
    The validate() method must be implemented by subclasses,
    There are some basic built-in cryptographic validation helpers which can be used if needed."""

    @abstractmethod
    def validate(self, token: str, context: Optional[ValidationContext] = None) -> ValidationResult:
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
        import base64, hashlib, hmac
        mac = hmac.new(key=secret.encode(), msg=message, digestmod=getattr(hashlib, algorithm))
        expected = base64.b64encode(mac.digest()).decode()
        return hmac.compare_digest(expected, signature)

    def _validate_rs256_jwt(
        self, token: str, public_key: str, audience: Optional[str] = None, issuer: Optional[str] = None, options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
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
