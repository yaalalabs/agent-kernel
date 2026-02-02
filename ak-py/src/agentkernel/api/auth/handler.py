from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import hmac
import hashlib
import base64
import jwt
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
        """Main validation entry point."""
        pass

    def _validate_hmac(self, message: bytes, signature: str, secret: str, algorithm: str = "sha256") -> bool:
        """Validates an HMAC signature."""
        mac = hmac.new(
            key=secret.encode(),
            msg=message,
            digestmod=getattr(hashlib, algorithm)
        )
        expected = base64.b64encode(mac.digest()).decode()
        return hmac.compare_digest(expected, signature)

    def _validate_rs256_jwt(self, token: str, public_key: str, audience: Optional[str] = None, 
                            issuer: Optional[str] = None, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Validates an RS256 JWT and returns decoded claims.
        Raises jwt exceptions if invalid."""
        return jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
            options=options or {},
        )