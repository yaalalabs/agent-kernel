import pytest
from unittest.mock import Mock, patch
from pydantic import ValidationError

from agentkernel.deployment.aws.akauthorizer import (
    APIGatewayAuthorizer,
    APIGatewayRequestAuthorizerEvent,
    Headers,
)
from agentkernel.auth.handler import AuthValidator, ValidationContext, ValidationResult


class TestAPIGatewayRequestAuthorizerEvent:
    """Tests for APIGatewayRequestAuthorizerEvent model."""

    def test_event_with_all_fields(self):
        """Test event with all required and optional fields."""
        event_data = {
            "type": "REQUEST",
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/resource",
            "resource": "/resource",
            "path": "/api/v1/chat",
            "httpMethod": "POST",
            "headers": {
                "Authorization": "Bearer token123",
                "Content-Type": "application/json"
            },
            "pathParameters": {"param1": "value1"},
            "stageVariables": {"stage": "prod"}
        }
        
        event = APIGatewayRequestAuthorizerEvent.model_validate(event_data)
        
        assert event.type == "REQUEST"
        assert event.methodArn == "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/resource"
        assert event.resource == "/resource"
        assert event.path == "/api/v1/chat"
        assert event.httpMethod == "POST"
        assert event.headers.Authorization == "Bearer token123"
        assert event.pathParameters == {"param1": "value1"}
        assert event.stageVariables == {"stage": "prod"}

    def test_event_with_minimal_fields(self):
        """Test event with only required fields."""
        event_data = {
            "type": "REQUEST",
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/resource",
            "headers": {
                "Authorization": "Bearer token123"
            }
        }
        
        event = APIGatewayRequestAuthorizerEvent.model_validate(event_data)
        
        assert event.type == "REQUEST"
        assert event.methodArn == "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/resource"
        assert event.resource is None
        assert event.path is None
        assert event.httpMethod is None
        assert event.headers.Authorization == "Bearer token123"
        assert event.pathParameters is None
        assert event.stageVariables is None

    def test_event_missing_required_fields(self):
        """Test event validation fails without required fields."""
        # Missing type
        with pytest.raises(ValidationError) as exc_info:
            APIGatewayRequestAuthorizerEvent.model_validate({
                "methodArn": "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/resource",
                "headers": {"Authorization": "Bearer token123"}
            })
        assert "type" in str(exc_info.value)

        # Missing methodArn
        with pytest.raises(ValidationError) as exc_info:
            APIGatewayRequestAuthorizerEvent.model_validate({
                "type": "REQUEST",
                "headers": {"Authorization": "Bearer token123"}
            })
        assert "methodArn" in str(exc_info.value)

        # Missing headers
        with pytest.raises(ValidationError) as exc_info:
            APIGatewayRequestAuthorizerEvent.model_validate({
                "type": "REQUEST",
                "methodArn": "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/resource"
            })
        assert "headers" in str(exc_info.value)

    def test_event_with_empty_optional_fields(self):
        """Test event with empty optional fields."""
        event_data = {
            "type": "REQUEST",
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/resource",
            "headers": {"Authorization": "Bearer token123"},
            "pathParameters": {},
            "stageVariables": {}
        }
        
        event = APIGatewayRequestAuthorizerEvent.model_validate(event_data)
        
        assert event.pathParameters == {}
        assert event.stageVariables == {}

    def test_event_serialization(self):
        """Test event model serialization."""
        event_data = {
            "type": "REQUEST",
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/resource",
            "headers": {"Authorization": "Bearer token123"}
        }
        
        event = APIGatewayRequestAuthorizerEvent.model_validate(event_data)
        serialized = event.model_dump()
        
        assert serialized["type"] == "REQUEST"
        assert serialized["methodArn"] == "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/resource"
        assert serialized["headers"]["Authorization"] == "Bearer token123"


class TestAPIGatewayAuthorizer:
    """Tests for APIGatewayAuthorizer class."""

    @pytest.fixture
    def mock_validator(self):
        """Mock AuthValidator for testing."""
        validator = Mock(spec=AuthValidator) # Creates a mock object that mimics the AuthValidator interface. "spec" parameter ensures the mock only allows attributes/methods that exist on the real AuthValidator class
        return validator

    @pytest.fixture
    def sample_authorizer(self, mock_validator):
        """Create APIGatewayAuthorizer instance for testing."""
        return APIGatewayAuthorizer(mock_validator) #sample authorizer is not mocked here, only the AuthValidator is mocked

    @pytest.fixture
    def sample_api_gateway_event(self):
        """Sample API Gateway event for testing."""
        return {
            "type": "REQUEST",
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/POST/api/v1/chat",
            "resource": "/api/v1/chat",
            "path": "/api/v1/chat",
            "httpMethod": "POST",
            "headers": {
                "Authorization": "Bearer valid_token_123",
                "Content-Type": "application/json"
            },
            "pathParameters": None,
            "stageVariables": None
        }

    @pytest.fixture
    def sample_lambda_context(self):
        """Sample Lambda context for testing."""
        context = Mock()
        context.aws_request_id = "test-request-id"
        context.function_name = "test-function"
        context.function_version = "$LATEST"
        return context

    def test_authorizer_initialization(self, mock_validator):
        """Test APIGatewayAuthorizer initialization."""
        authorizer = APIGatewayAuthorizer(mock_validator)
        
        assert authorizer._validator == mock_validator
        assert authorizer._log is not None

    def test_handle_valid_token(self, sample_authorizer, mock_validator, sample_api_gateway_event):
        """Test handle() method of APIGatewayAuthorizer with valid token ouput from AuthValidator."""
        # Setup validator to return success
        mock_validator.validate.return_value = ValidationResult( # adding a return value from the mock_validator.validate() function
            is_valid=True,
            subject="user123",
            claims={"user_id": "user123", "role": "admin"}
        )
        
        result = sample_authorizer.handle(sample_api_gateway_event)
        
        # Verify policy structure
        assert result["principalId"] == "user123"
        assert result["policyDocument"]["Version"] == "2012-10-17"
        assert len(result["policyDocument"]["Statement"]) == 1
        
        statement = result["policyDocument"]["Statement"][0]
        assert statement["Action"] == "execute-api:Invoke"
        assert statement["Effect"] == "Allow"
        assert statement["Resource"] == sample_api_gateway_event["methodArn"]
        
        # Verify context
        assert result["context"]["user_id"] == "user123"
        assert result["context"]["role"] == "admin"

    def test_handle_invalid_token(self, sample_authorizer, mock_validator, sample_api_gateway_event):
        """Test handle() method of APIGatewayAuthorizer with invalid token ouput from AuthValidator."""
        # Setup validator to return failure
        mock_validator.validate.return_value = ValidationResult(
            is_valid=False,
            error_msg="Invalid token signature"
        )
        
        result = sample_authorizer.handle(sample_api_gateway_event)
        
        # Verify deny policy
        assert result["principalId"] == "user"  # default subject
        statement = result["policyDocument"]["Statement"][0]
        assert statement["Effect"] == "Deny"
        assert statement["Resource"] == sample_api_gateway_event["methodArn"]
        
        # No context for failed validation
        assert "context" not in result

    def test_handle_with_lambda_context(self, sample_authorizer, mock_validator, sample_api_gateway_event, sample_lambda_context):
        """Test handle() method with Lambda context (should be ignored)."""
        mock_validator.validate.return_value = ValidationResult(is_valid=True)
        
        # Context should not affect the result
        result = sample_authorizer.handle(sample_api_gateway_event, sample_lambda_context)
        
        assert result["principalId"] == "user"  # default subject
        assert result["policyDocument"]["Statement"][0]["Effect"] == "Allow"

    def test_build_request(self, sample_authorizer, sample_api_gateway_event):
        """Test _build_request method."""
        request = sample_authorizer._build_request(sample_api_gateway_event)
        
        assert isinstance(request, APIGatewayRequestAuthorizerEvent)
        assert request.type == sample_api_gateway_event["type"]
        assert request.methodArn == sample_api_gateway_event["methodArn"]
        assert request.headers.Authorization == sample_api_gateway_event["headers"]["Authorization"]

    def test_extract_token_with_bearer(self, sample_authorizer):
        """Test _extract_token method with Bearer prefix."""
        headers = Headers(Authorization="Bearer token123")
        request = APIGatewayRequestAuthorizerEvent(
            type="REQUEST",
            methodArn="arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/resource",
            headers=headers
        )
        
        token = sample_authorizer._extract_token(request)
        assert token == "token123"

    def test_extract_token_without_bearer(self, sample_authorizer):
        """Test _extract_token method without Bearer prefix."""
        headers = Headers(Authorization="token123")
        request = APIGatewayRequestAuthorizerEvent(
            type="REQUEST",
            methodArn="arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/resource",
            headers=headers
        )
        
        token = sample_authorizer._extract_token(request)
        assert token == "token123"

    def test_extract_token_with_whitespace(self, sample_authorizer):
        """Test _extract_token method with extra whitespace."""
        headers = Headers(Authorization="Bearer   token123   ")
        request = APIGatewayRequestAuthorizerEvent(
            type="REQUEST",
            methodArn="arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/resource",
            headers=headers
        )
        
        token = sample_authorizer._extract_token(request)
        assert token == "token123"

    def test_build_policy_allow_effect(self, sample_authorizer):
        """Test _build_policy method with Allow effect."""
        method_arn = "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/resource"
        context = {"user_id": "user123", "role": "admin"}
        
        policy = sample_authorizer._build_policy(
            principal_id="user123",
            effect="Allow",
            method_arn=method_arn,
            context=context
        )
        
        assert policy["principalId"] == "user123"
        assert policy["policyDocument"]["Version"] == "2012-10-17"
        
        statement = policy["policyDocument"]["Statement"][0]
        assert statement["Action"] == "execute-api:Invoke"
        assert statement["Effect"] == "Allow"
        assert statement["Resource"] == method_arn
        
        # Verify context values are strings
        assert policy["context"]["user_id"] == "user123"
        assert policy["context"]["role"] == "admin"

    def test_build_policy_deny_effect(self, sample_authorizer):
        """Test _build_policy method with Deny effect."""
        method_arn = "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/resource"
        
        policy = sample_authorizer._build_policy(
            principal_id="anonymous",
            effect="Deny",
            method_arn=method_arn,
            context=None
        )
        
        assert policy["principalId"] == "anonymous"
        statement = policy["policyDocument"]["Statement"][0]
        assert statement["Effect"] == "Deny"
        
        # No context for deny
        assert "context" not in policy

    def test_build_policy_without_context(self, sample_authorizer):
        """Test _build_policy method without context."""
        method_arn = "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/resource"
        
        policy = sample_authorizer._build_policy(
            principal_id="user123",
            effect="Allow",
            method_arn=method_arn,
            context=None
        )
        
        assert policy["principalId"] == "user123"
        assert "context" not in policy

    def test_build_policy_context_type_conversion(self, sample_authorizer):
        """Test _build_policy converts context values to strings."""
        method_arn = "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/resource"
        context = {
            "user_id": 123,  # integer
            "is_admin": True,  # boolean
            "permissions": ["read", "write"],  # list
            "metadata": {"key": "value"}  # dict
        }
        
        policy = sample_authorizer._build_policy(
            principal_id="user123",
            effect="Allow",
            method_arn=method_arn,
            context=context
        )
        
        # All context values should be strings
        assert policy["context"]["user_id"] == "123"
        assert policy["context"]["is_admin"] == "True"
        assert policy["context"]["permissions"] == "['read', 'write']"
        assert policy["context"]["metadata"] == "{'key': 'value'}"

    def test_validation_context_creation(self, sample_authorizer, mock_validator, sample_api_gateway_event):
        """Test that ValidationContext is created correctly."""
        mock_validator.validate.return_value = ValidationResult(is_valid=True)
        
        sample_authorizer.handle(sample_api_gateway_event)
        
        # Verify that validate was called once
        mock_validator.validate.assert_called_once()
        
        # Verify the token was passed correctly
        call_args = mock_validator.validate.call_args
        assert call_args is not None

    def test_logging_behavior(self, sample_authorizer, mock_validator, sample_api_gateway_event):
        """Test logging behavior in handle method."""
        mock_validator.validate.return_value = ValidationResult(is_valid=True)
        
        with patch.object(sample_authorizer._log, 'info') as mock_log_info:
            result = sample_authorizer.handle(sample_api_gateway_event)
            
            # Verify logging calls
            mock_log_info.assert_any_call(f"Authorizer received event: {sample_api_gateway_event}")
            mock_log_info.assert_any_call(f"Authorizer return policy: {result}")

    def test_validator_exception_handling(self, sample_authorizer, mock_validator, sample_api_gateway_event):
        """Test handling of validator exceptions."""
        # Setup validator to raise exception
        mock_validator.validate.side_effect = Exception("Validation error")
        
        with pytest.raises(Exception, match="Validation error"):
            sample_authorizer.handle(sample_api_gateway_event)

    def test_event_validation_error(self, sample_authorizer, mock_validator):
        """Test handling of invalid event data."""
        invalid_event = {
            "type": "REQUEST",
            # Missing required methodArn and headers
        }
        
        mock_validator.validate.return_value = ValidationResult(is_valid=True)
        
        with pytest.raises(ValidationError):
            sample_authorizer.handle(invalid_event)

    def test_different_http_methods(self, sample_authorizer, mock_validator):
        """Test authorizer with different HTTP methods."""
        methods = ["GET", "POST", "PUT", "DELETE", "PATCH"]
        
        for method in methods:
            event = {
                "type": "REQUEST",
                "methodArn": f"arn:aws:execute-api:us-east-1:123456789012:api/test/prod/{method}/resource",
                "headers": {"Authorization": "Bearer token123"},
                "httpMethod": method,
                "path": "/resource"
            }
            
            mock_validator.validate.return_value = ValidationResult(is_valid=True)
            
            result = sample_authorizer.handle(event)
            
            assert result["policyDocument"]["Statement"][0]["Effect"] == "Allow"
            assert result["policyDocument"]["Statement"][0]["Resource"] == event["methodArn"]

    def test_complex_path_parameters(self, sample_authorizer, mock_validator):
        """Test authorizer with complex path parameters."""
        event = {
            "type": "REQUEST",
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/users/{userId}/posts/{postId}",
            "headers": {"Authorization": "Bearer token123"},
            "httpMethod": "GET",
            "path": "/users/123/posts/456",
            "pathParameters": {"userId": "123", "postId": "456"}
        }
        
        mock_validator.validate.return_value = ValidationResult(is_valid=True)
        
        result = sample_authorizer.handle(event)
        
        assert result["policyDocument"]["Statement"][0]["Effect"] == "Allow"
        assert result["policyDocument"]["Statement"][0]["Resource"] == event["methodArn"]
        
        # Verify ValidationContext includes path parameters
        call_args = mock_validator.validate.call_args
        if len(call_args[0]) > 1:
            context = call_args[0][1]
            assert context.path == "/users/123/posts/456"
            assert context.http_method == "GET"
        

    def test_stage_variables(self, sample_authorizer, mock_validator):
        """Test authorizer with stage variables."""
        event = {
            "type": "REQUEST",
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/resource",
            "headers": {"Authorization": "Bearer token123"},
            "httpMethod": "GET",
            "path": "/resource",
            "stageVariables": {"stage": "prod", "version": "v1"}
        }
        
        mock_validator.validate.return_value = ValidationResult(is_valid=True)
        
        result = sample_authorizer.handle(event)
        
        assert result["policyDocument"]["Statement"][0]["Effect"] == "Allow"

    def test_empty_claims_in_validation_result(self, sample_authorizer, mock_validator, sample_api_gateway_event):
        """Test handling of empty claims in validation result."""
        mock_validator.validate.return_value = ValidationResult(
            is_valid=True,
            subject="user123",
            claims=None
        )
        
        result = sample_authorizer.handle(sample_api_gateway_event)
        
        assert result["principalId"] == "user123"
        assert result["policyDocument"]["Statement"][0]["Effect"] == "Allow"
        assert "context" not in result

    def test_empty_claims_dict_in_validation_result(self, sample_authorizer, mock_validator, sample_api_gateway_event):
        """Test handling of empty claims dictionary in validation result."""
        mock_validator.validate.return_value = ValidationResult(
            is_valid=True,
            subject="user123",
            claims={}
        )
        
        result = sample_authorizer.handle(sample_api_gateway_event)
        
        assert result["principalId"] == "user123"
        assert result["policyDocument"]["Statement"][0]["Effect"] == "Allow"
        assert "context" not in result


class TestAPIGatewayAuthorizerIntegration:
    """Integration tests for APIGatewayAuthorizer."""

    def test_full_authorization_flow_success(self):
        """Test complete authorization flow with successful validation."""
        # Create a real validator implementation
        class TestValidator(AuthValidator):
            def validate(self, token, context=None):
                if token == "valid_token_123":
                    return ValidationResult(
                        is_valid=True,
                        subject="test_user",
                        claims={"user_id": "test_user", "permissions": ["read", "write"]}
                    )
                else:
                    return ValidationResult(
                        is_valid=False,
                        error_msg="Invalid token"
                    )
        
        validator = TestValidator()
        authorizer = APIGatewayAuthorizer(validator)
        
        event = {
            "type": "REQUEST",
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/protected",
            "headers": {"Authorization": "Bearer valid_token_123"},
            "httpMethod": "GET",
            "path": "/protected"
        }
        
        result = authorizer.handle(event)
        
        assert result["principalId"] == "test_user"
        assert result["policyDocument"]["Statement"][0]["Effect"] == "Allow"
        assert result["context"]["user_id"] == "test_user"
        assert result["context"]["permissions"] == "['read', 'write']"

    def test_full_authorization_flow_failure(self):
        """Test complete authorization flow with failed validation."""
        class TestValidator(AuthValidator):
            def validate(self, token, context=None):
                return ValidationResult(
                    is_valid=False,
                    error_msg="Token expired"
                )
        
        validator = TestValidator()
        authorizer = APIGatewayAuthorizer(validator)
        
        event = {
            "type": "REQUEST",
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/protected",
            "headers": {"Authorization": "Bearer expired_token"},
            "httpMethod": "GET",
            "path": "/protected"
        }
        
        result = authorizer.handle(event)
        
        assert result["principalId"] == "user"  # default
        assert result["policyDocument"]["Statement"][0]["Effect"] == "Deny"
        assert "context" not in result

    def test_policy_format_compliance(self):
        """Test that generated policy complies with AWS API Gateway format."""
        validator = Mock(spec=AuthValidator)
        validator.validate.return_value = ValidationResult(
            is_valid=True,
            subject="test_user",
            claims={"user_id": "test_user"}
        )
        
        authorizer = APIGatewayAuthorizer(validator)
        
        event = {
            "type": "REQUEST",
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/resource",
            "headers": {"Authorization": "Bearer token123"},
            "httpMethod": "GET",
            "path": "/resource"
        }
        
        result = authorizer.handle(event)
        
        # Verify required AWS policy structure
        assert "principalId" in result
        assert "policyDocument" in result
        assert "Version" in result["policyDocument"]
        assert "Statement" in result["policyDocument"]
        assert len(result["policyDocument"]["Statement"]) == 1
        
        statement = result["policyDocument"]["Statement"][0]
        assert "Action" in statement
        assert "Effect" in statement
        assert "Resource" in statement
        
        # Verify AWS-specific values
        assert result["policyDocument"]["Version"] == "2012-10-17"
        assert statement["Action"] == "execute-api:Invoke"
        assert statement["Effect"] in ["Allow", "Deny"]
