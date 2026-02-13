import base64
import hashlib
import hmac
from unittest.mock import patch
from typing import Optional

import jwt
import pytest

from agentkernel.auth.handler import (
    AuthValidator,
    ValidationContext,
    ValidationResult,
)


class CustomAuthTokenValidator(AuthValidator):
    """Custom JWT token validator for testing."""
    
    def validate(self, token: str, context: Optional[ValidationContext] = None) -> ValidationResult:
        """Validate JWT token and return validation result."""
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            print("Payload", payload)
            email = payload.get("email", "")
            if email == "test@test.com":
                return ValidationResult(is_valid=True, subject=email, claims=payload)
            return ValidationResult(is_valid=False, error_msg=f"Invalid email: {email}")
        except jwt.InvalidTokenError as e:
            return ValidationResult(is_valid=False, error_msg=f"Invalid token: {str(e)}")
    
    @staticmethod
    def generate_test_token(email: str = "test@test.com") -> str:
        """Generate a test JWT token with specified email."""
        payload = {
            "email": email,
            "sub": "user123",
            "iat": 1234567890,
            "exp": 9999999999
        }
        return jwt.encode(payload, "test_secret", algorithm="HS256")


class TestValidationContext:
    """Tests for ValidationContext model."""

    def test_validation_context_with_all_fields(self):
        """Test ValidationContext with all fields provided."""
        context = ValidationContext(
            path="/api/v1/chat", http_method="POST", headers={"authorization": "Bearer token123", "content-type": "application/json"}
        )
        assert context.path == "/api/v1/chat"
        assert context.http_method == "POST"
        assert context.headers == {"authorization": "Bearer token123", "content-type": "application/json"}

    def test_validation_context_with_partial_fields(self):
        """Test ValidationContext with only headers."""
        context = ValidationContext(headers={"authorization": "Bearer token123"})
        assert context.path is None
        assert context.http_method is None
        assert context.headers == {"authorization": "Bearer token123"}

    def test_validation_context_empty_headers(self):
        """Test ValidationContext with empty headers."""
        context = ValidationContext(headers={})
        assert context.headers == {}

    def test_validation_context_serialization(self):
        """Test ValidationContext serialization."""
        context = ValidationContext(path="/test", http_method="GET", headers={"x-custom": "value"})
        data = context.model_dump()
        assert data["path"] == "/test"
        assert data["http_method"] == "GET"
        assert data["headers"] == {"x-custom": "value"}


class TestValidationResult:
    """Tests for ValidationResult model."""

    def test_validation_result_success(self):
        """Test ValidationResult for successful validation."""
        result = ValidationResult(is_valid=True, subject="user123", claims={"user_id": "user123", "role": "admin"})
        assert result.is_valid is True
        assert result.subject == "user123"
        assert result.claims == {"user_id": "user123", "role": "admin"}
        assert result.error_msg is None

    def test_validation_result_failure(self):
        """Test ValidationResult for failed validation."""
        result = ValidationResult(is_valid=False, error_msg="Invalid token signature")
        assert result.is_valid is False
        assert result.subject == "user"  # default value
        assert result.claims is None
        assert result.error_msg == "Invalid token signature"

    def test_validation_result_default_values(self):
        """Test ValidationResult with default values."""
        result = ValidationResult(is_valid=True)
        assert result.is_valid is True
        assert result.subject == "user"
        assert result.claims is None
        assert result.error_msg is None

    def test_validation_result_empty_claims(self):
        """Test ValidationResult with empty claims."""
        result = ValidationResult(is_valid=True, claims={})
        assert result.claims == {}


class TestAuthValidator:
    """Tests for AuthValidator abstract class."""

    def test_auth_validator_is_abstract(self):
        """Test that AuthValidator cannot be instantiated directly."""
        with pytest.raises(TypeError) as exc_info:
            AuthValidator()
        assert "Can't instantiate abstract class" in str(exc_info.value)
        assert "validate" in str(exc_info.value)

    def test_validate_hmac_valid_signature(self):
        """Test _validate_hmac with valid signature."""

        # Create a concrete implementation for testing
        class TestValidator(AuthValidator):
            def validate(self, token, context=None):
                return ValidationResult(is_valid=True)

        validator = TestValidator()
        message = b"test message"
        secret = "test_secret"

        # Generate valid HMAC
        mac = hmac.new(key=secret.encode(), msg=message, digestmod=hashlib.sha256)
        signature = base64.b64encode(mac.digest()).decode()

        result = validator._validate_hmac(message, signature, secret)
        assert result is True

    def test_validate_hmac_invalid_signature(self):
        """Test _validate_hmac with invalid signature."""

        class TestValidator(AuthValidator):
            def validate(self, token, context=None):
                return ValidationResult(is_valid=True)

        validator = TestValidator()
        message = b"test message"
        secret = "test_secret"
        invalid_signature = "invalid_signature"

        result = validator._validate_hmac(message, invalid_signature, secret)
        assert result is False

    def test_validate_hmac_different_algorithms(self):
        """Test _validate_hmac with different hash algorithms."""

        class TestValidator(AuthValidator):
            def validate(self, token, context=None):
                return ValidationResult(is_valid=True)

        validator = TestValidator()
        message = b"test message"  # gives this text as bytes
        secret = "test_secret"

        # Test with sha1
        mac = hmac.new(key=secret.encode(), msg=message, digestmod=hashlib.sha1)
        signature = base64.b64encode(mac.digest()).decode()

        result = validator._validate_hmac(message, signature, secret, "sha1")
        assert result is True

    def test_validate_hmac_unicode_handling(self):
        """Test _validate_hmac with unicode characters."""

        class TestValidator(AuthValidator):
            def validate(self, token, context=None):
                return ValidationResult(is_valid=True)

        validator = TestValidator()
        message = "test message with unicode: 🚀".encode("utf-8")
        secret = "test_secret_unicode_🔑"

        mac = hmac.new(key=secret.encode(), msg=message, digestmod=hashlib.sha256)
        signature = base64.b64encode(mac.digest()).decode()

        result = validator._validate_hmac(message, signature, secret)
        assert result is True

    def test_validate_rs256_jwt_valid_token(self):
        """Test _validate_rs256_jwt with valid JWT token."""

        class TestValidator(AuthValidator):
            def validate(self, token, context=None):
                return ValidationResult(is_valid=True)

        validator = TestValidator()

        # Create a valid JWT token for testing
        public_key = "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAzK8l7K..."

        # Mock jwt.decode to avoid needing real keys
        with patch(
            "jwt.decode"
        ) as mock_decode:  # Using the patch() function (from unittest.mock) replaces the real jwt.decode function with a mock object
            mock_decode.return_value = {"user_id": "test_user", "role": "admin"}

            result = validator._validate_rs256_jwt(token="fake_jwt_token", public_key=public_key, audience="test_audience", issuer="test_issuer")

            assert result == {"user_id": "test_user", "role": "admin"}
            mock_decode.assert_called_once_with(  # verifies that the mock function was called exactly once with specific arguments
                "fake_jwt_token", public_key, algorithms=["RS256"], audience="test_audience", issuer="test_issuer", options={}
            )

    def test_validate_rs256_jwt_with_options(self):
        """Test _validate_rs256_jwt with custom options."""

        class TestValidator(AuthValidator):
            def validate(self, token, context=None):
                return ValidationResult(is_valid=True)

        validator = TestValidator()

        with patch("jwt.decode") as mock_decode:
            mock_decode.return_value = {"user_id": "test_user"}

            options = {"verify_signature": False}
            result = validator._validate_rs256_jwt(token="fake_jwt_token", public_key="public_key", options=options)

            assert result == {"user_id": "test_user"}
            mock_decode.assert_called_once_with("fake_jwt_token", "public_key", algorithms=["RS256"], audience=None, issuer=None, options=options)

    def test_validate_rs256_jwt_invalid_token(self):
        """Test _validate_rs256_jwt with invalid JWT token."""

        class TestValidator(AuthValidator):
            def validate(self, token, context=None):
                return ValidationResult(is_valid=True)

        validator = TestValidator()

        with patch("jwt.decode") as mock_decode:
            mock_decode.side_effect = jwt.InvalidTokenError("Invalid token")

            with pytest.raises(jwt.InvalidTokenError):
                validator._validate_rs256_jwt(token="invalid_token", public_key="public_key")

    def test_validate_rs256_jwt_expired_token(self):
        """Test _validate_rs256_jwt with expired JWT token."""

        class TestValidator(AuthValidator):
            def validate(self, token, context=None):
                return ValidationResult(is_valid=True)

        validator = TestValidator()

        with patch("jwt.decode") as mock_decode:
            mock_decode.side_effect = jwt.ExpiredSignatureError("Token has expired")

            with pytest.raises(jwt.ExpiredSignatureError):
                validator._validate_rs256_jwt(token="expired_token", public_key="public_key")


class TestCustomAuthValidator:
    """Tests for CustomAuthTokenValidator implementation."""

    @pytest.fixture
    def custom_validator(self):
        """Create a CustomAuthTokenValidator instance for testing."""
        return CustomAuthTokenValidator()

    def test_validate_with_valid_email_token(self, custom_validator):
        """Test validate method with valid JWT token containing correct email."""
        # Generate token with correct email
        valid_token = CustomAuthTokenValidator.generate_test_token("test@test.com")
        
        result = custom_validator.validate(valid_token)

        assert result.is_valid is True
        assert result.subject == "test@test.com"
        assert result.claims["email"] == "test@test.com"
        assert result.error_msg is None

    def test_validate_with_invalid_email_token(self, custom_validator):
        """Test validate method with JWT token containing wrong email."""
        # Generate token with wrong email
        invalid_token = CustomAuthTokenValidator.generate_test_token("wrong@email.com")
        
        result = custom_validator.validate(invalid_token)

        assert result.is_valid is False
        assert result.subject == "user"  # default
        assert result.claims is None
        assert "Invalid email: wrong@email.com" in result.error_msg

    def test_validate_with_malformed_token(self, custom_validator):
        """Test validate method with malformed JWT token."""
        malformed_token = "this.is.not.a.valid.jwt.token"
        
        result = custom_validator.validate(malformed_token)

        assert result.is_valid is False
        assert result.subject == "user"  # default
        assert result.claims is None
        assert "Invalid token:" in result.error_msg

    def test_validate_with_empty_token(self, custom_validator):
        """Test validate method with empty token."""
        result = custom_validator.validate("")

        assert result.is_valid is False
        assert result.subject == "user"  # default
        assert result.claims is None
        assert "Invalid token:" in result.error_msg

    def test_validate_with_none_token(self, custom_validator):
        """Test validate method with None token."""
        result = custom_validator.validate(None)

        assert result.is_valid is False
        assert result.subject == "user"  # default
        assert result.claims is None
        assert "Invalid token:" in result.error_msg

    def test_validate_with_context(self, custom_validator):
        """Test validate method with ValidationContext."""
        valid_token = CustomAuthTokenValidator.generate_test_token("test@test.com")
        context = ValidationContext(path="/api/v1/chat", http_method="POST", headers={"authorization": f"Bearer {valid_token}"})

        result = custom_validator.validate(valid_token, context)

        assert result.is_valid is True
        assert result.subject == "test@test.com"
        assert result.claims["email"] == "test@test.com"

    def test_validate_without_context(self, custom_validator):
        """Test validate method without ValidationContext."""
        valid_token = CustomAuthTokenValidator.generate_test_token("test@test.com")
        result = custom_validator.validate(valid_token)

        assert result.is_valid is True
        assert result.subject == "test@test.com"

    def test_generate_test_token_with_default_email(self):
        """Test token generation with default email."""
        token = CustomAuthTokenValidator.generate_test_token()
        
        # Decode to verify payload
        payload = jwt.decode(token, options={"verify_signature": False})
        
        assert payload["email"] == "test@test.com"
        assert payload["sub"] == "user123"
        assert "iat" in payload
        assert "exp" in payload

    def test_generate_test_token_with_custom_email(self):
        """Test token generation with custom email."""
        custom_email = "custom@example.com"
        token = CustomAuthTokenValidator.generate_test_token(custom_email)
        
        # Decode to verify payload
        payload = jwt.decode(token, options={"verify_signature": False})
        
        assert payload["email"] == custom_email
        assert payload["sub"] == "user123"

    def test_validate_token_without_email_claim(self, custom_validator):
        """Test validate method with JWT token missing email claim."""
        # Generate token without email claim
        payload = {
            "sub": "user123",
            "name": "Test User",
            "iat": 1234567890,
            "exp": 9999999999
        }
        token_without_email = jwt.encode(payload, "test_secret", algorithm="HS256")
        
        result = custom_validator.validate(token_without_email)

        assert result.is_valid is False
        assert result.subject == "user"  # default
        assert result.claims is None
        assert "Invalid email:" in result.error_msg


class TestAuthValidatorIntegration:
    """Integration tests for AuthValidator components."""

    def test_validation_flow_with_hmac(self):
        """Test complete validation flow using HMAC."""

        class HMACValidator(AuthValidator):
            def validate(self, token, context=None):
                # Simulate HMAC validation
                message = f"{token}:{context.path if context else ''}".encode()
                signature = context.headers.get("x-signature", "") if context else ""

                if self._validate_hmac(message, signature, "secret"):
                    return ValidationResult(is_valid=True, subject="hmac_user", claims={"method": "hmac"})
                else:
                    return ValidationResult(is_valid=False, error_msg="HMAC validation failed")

        validator = HMACValidator()
        context = ValidationContext(path="/api/v1/test", headers={"x-signature": "invalid_signature"})

        result = validator.validate("test_token", context)
        assert result.is_valid is False
        assert result.error_msg == "HMAC validation failed"

    def test_validation_flow_with_jwt(self):
        """Test complete validation flow using JWT."""

        class JWTValidator(AuthValidator):
            def validate(self, token, context=None):
                try:
                    claims = self._validate_rs256_jwt(token=token, public_key="test_public_key", audience="test_audience")
                    return ValidationResult(is_valid=True, subject=claims.get("sub", "unknown"), claims=claims)
                except jwt.InvalidTokenError as e:
                    return ValidationResult(is_valid=False, error_msg=str(e))

        validator = JWTValidator()

        with patch.object(validator, "_validate_rs256_jwt") as mock_jwt_validate:
            mock_jwt_validate.return_value = {"sub": "jwt_user", "aud": "test_audience"}

            result = validator.validate("valid_jwt")
            assert result.is_valid is True
            assert result.subject == "jwt_user"
            assert result.claims == {"sub": "jwt_user", "aud": "test_audience"}

    def test_validator_error_handling(self):
        """Test validator error handling and logging."""

        class ErrorValidator(AuthValidator):
            def validate(self, token, context=None):
                raise Exception("Unexpected validation error")

        validator = ErrorValidator()

        with pytest.raises(Exception, match="Unexpected validation error"):
            validator.validate("any_token")
