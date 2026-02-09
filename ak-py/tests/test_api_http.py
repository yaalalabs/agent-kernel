from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.testclient import TestClient

from agentkernel.api.http import RESTAPI
from agentkernel.auth.handler import AuthValidator, ValidationContext, ValidationResult


class TestRESTAPI:
    """Tests for RESTAPI class."""

    @pytest.fixture
    def mock_config(self):
        """Mock AKConfig for testing."""
        config = Mock()
        config.api.host = "localhost"
        config.api.port = 8000
        config.api.custom_router_prefix = "/custom"
        config.a2a.enabled = False
        config.mcp.enabled = False
        return config

    @pytest.fixture
    def mock_auth_validator(self):
        """Mock AuthValidator for testing."""
        validator = Mock(spec=AuthValidator)
        validator.validate.return_value = ValidationResult(is_valid=True, subject="test_user", claims={"user_id": "test_user"})
        return validator

    @pytest.fixture
    def sample_router(self):
        """Create a sample FastAPI router for testing."""
        router = APIRouter()

        @router.get("/test")
        def test_endpoint():
            return {"message": "test"}

        @router.post("/test-post")
        def test_post_endpoint():
            return {"message": "post test"}

        return router

    def test_create_app_basic(self):
        """Test _create_app with basic configuration."""
        routers = []
        app = RESTAPI._create_app(routers)

        assert isinstance(app, FastAPI)
        assert app.title == "Agent Kernel REST API"
        assert app.debug is True

    def test_create_app_with_routers(self, sample_router):
        """Test _create_app with routers."""
        routers = [sample_router]
        app = RESTAPI._create_app(routers)

        # Test that the router was included
        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200
        assert response.json() == {"message": "test"}

    def test_create_app_with_lifespan(self):
        """Test _create_app with lifespan handler."""

        async def lifespan(app):
            pass

        routers = []
        app = RESTAPI._create_app(routers, lifespan=lifespan)

        # FastAPI doesn't expose lifespan_context directly, but we can verify the app was created
        assert isinstance(app, FastAPI)

    def test_create_app_cors_middleware(self):
        """Test that CORS middleware is properly configured."""
        routers = []
        app = RESTAPI._create_app(routers)

        # Check if CORS middleware was added
        cors_middleware = None
        for middleware in app.user_middleware:
            if middleware.cls == CORSMiddleware:
                cors_middleware = middleware
                break

        assert cors_middleware is not None
        assert cors_middleware.kwargs["allow_origins"] == ["*"]
        assert cors_middleware.kwargs["allow_credentials"] is True
        assert cors_middleware.kwargs["allow_methods"] == ["*"]
        assert cors_middleware.kwargs["allow_headers"] == ["*"]

    def test_create_app_openapi_endpoint(self):
        """Test OpenAPI endpoint generation."""
        routers = []
        app = RESTAPI._create_app(routers)

        client = TestClient(app)
        response = client.get("/openapi.json")
        assert response.status_code == 200

        openapi_data = response.json()
        assert openapi_data["info"]["title"] == "Agent Kernel REST API"
        # Version might be different, just check it exists
        assert "version" in openapi_data["info"]

    def test_add_custom_router(self, sample_router):
        """Test adding custom router to RESTAPI."""
        # Clear any existing routers
        RESTAPI._custom_routers.clear()

        RESTAPI.add(sample_router)

        assert len(RESTAPI._custom_routers) == 1
        assert RESTAPI._custom_routers[0] == sample_router

    def test_add_multiple_custom_routers(self, sample_router):
        """Test adding multiple custom routers."""
        RESTAPI._custom_routers.clear()

        router2 = APIRouter()

        @router2.get("/test2")
        def test2():
            return {"message": "test2"}

        RESTAPI.add(sample_router)
        RESTAPI.add(router2)

        assert len(RESTAPI._custom_routers) == 2

    @patch("agentkernel.api.http.AKConfig")
    def test_run_with_default_handlers(self, mock_config_class, mock_config):
        """Test run method with default handlers."""
        mock_config_class.get.return_value = mock_config

        with patch("uvicorn.run") as mock_uvicorn:
            RESTAPI.run()

            # Verify uvicorn.run was called
            mock_uvicorn.assert_called_once()
            args, kwargs = mock_uvicorn.call_args
            assert kwargs["host"] == "localhost"
            assert kwargs["port"] == 8000
            assert kwargs["reload"] is False

    @patch("agentkernel.api.http.AKConfig")
    def test_run_with_custom_handlers(self, mock_config_class, mock_config):
        """Test run method with custom handlers."""
        mock_config_class.get.return_value = mock_config

        mock_handler = Mock()
        mock_router = APIRouter()

        @mock_router.get("/custom")
        def custom_endpoint():
            return {"message": "custom"}

        mock_handler.get_router.return_value = mock_router

        with patch("uvicorn.run") as mock_uvicorn:
            RESTAPI.run([mock_handler])

            mock_uvicorn.assert_called_once()
            app = mock_uvicorn.call_args[1]["app"]

            # Test that custom endpoint is available
            client = TestClient(app)
            response = client.get("/custom")
            assert response.status_code == 200

    def test_add_auth_handlers_with_validators(self, mock_auth_validator):
        """Test add_auth_handlers with auth validators."""
        RESTAPI._auth_token_validators.clear()

        validators = [mock_auth_validator]
        RESTAPI.add_auth_handlers(validators)

        assert len(RESTAPI._auth_token_validators) == 1

    def test_add_auth_handlers_empty_list(self):
        """Test add_auth_handlers with empty validator list."""
        RESTAPI._auth_token_validators.clear()

        RESTAPI.add_auth_handlers([])

        assert len(RESTAPI._auth_token_validators) == 0

    def test_add_auth_handlers_multiple_validators(self, mock_auth_validator):
        """Test add_auth_handlers with multiple validators."""
        RESTAPI._auth_token_validators.clear()

        validator2 = Mock(spec=AuthValidator)
        validator2.validate.return_value = ValidationResult(is_valid=True)

        validators = [mock_auth_validator, validator2]
        RESTAPI.add_auth_handlers(validators)

        assert len(RESTAPI._auth_token_validators) == 2


class TestRESTAPIAuthentication:
    """Tests for RESTAPI authentication functionality."""

    @pytest.fixture
    def mock_auth_validator(self):
        """Mock AuthValidator for authentication testing."""
        validator = Mock(spec=AuthValidator)
        return validator

    @pytest.fixture
    def sample_app(self):
        """Create a sample FastAPI app for testing authentication."""
        app = FastAPI()

        @app.get("/protected")
        def protected_endpoint():
            return {"message": "protected data"}

        @app.get("/public")
        def public_endpoint():
            return {"message": "public data"}

        return app

    def test_auth_function_creation(self, mock_auth_validator):
        """Test that auth function is created correctly."""
        RESTAPI._auth_token_validators.clear()

        RESTAPI.add_auth_handlers([mock_auth_validator])

        assert len(RESTAPI._auth_token_validators) == 1
        # Just verify that validators were added, not the specific type

    def test_token_validation_with_whitespace(self, mock_auth_validator):
        """Test token validation with extra whitespace."""
        # Set up the mock validator to capture the actual token
        captured_token = None

        def capture_token(token, context=None):
            nonlocal captured_token
            captured_token = token
            return ValidationResult(is_valid=True, subject="test_user")

        mock_auth_validator.validate.side_effect = capture_token

        RESTAPI._auth_token_validators.clear()
        RESTAPI.add_auth_handlers([mock_auth_validator])

        # Get the auth function that was created
        auth_dependency = RESTAPI._auth_token_validators[0]
        auth_function = auth_dependency.dependency

        # Create a mock request with whitespace in token
        mock_request = Mock()
        mock_request.url = "http://localhost:8000/protected"
        mock_request.method = "GET"
        mock_request.headers = {"authorization": "Bearer   token_with_spaces   "}

        # Call the auth function directly
        result = auth_function(mock_request)

        # Verify the token was properly stripped before validation
        assert captured_token == "token_with_spaces"
        assert captured_token != "Bearer   token_with_spaces   "

        # Verify the validation result
        assert result.is_valid is True
        assert result.subject == "test_user"


class TestRESTAPIIntegration:
    """Integration tests for RESTAPI functionality."""

    @patch("agentkernel.api.http.AKConfig")
    def test_full_app_creation_with_auth(self, mock_config_class):
        """Test full app creation with authentication."""
        mock_config = Mock()
        mock_config.api.host = "localhost"
        mock_config.api.port = 8000
        mock_config.api.custom_router_prefix = "/custom"
        mock_config.a2a.enabled = False
        mock_config.mcp.enabled = False
        mock_config_class.get.return_value = mock_config

        # Create a mock validator
        validator = Mock(spec=AuthValidator)
        validator.validate.return_value = ValidationResult(is_valid=True)

        # Add auth handlers
        RESTAPI._auth_token_validators.clear()
        RESTAPI.add_auth_handlers([validator])

        # Create app
        routers = []
        app = RESTAPI._create_app(routers)

        # Test that app was created successfully
        assert isinstance(app, FastAPI)
        route_paths = [route.path for route in app.routes]
        assert "/health" in route_paths
        assert len(RESTAPI._auth_token_validators) == 1
        assert RESTAPI._auth_token_validators[0].dependency is not None

    @patch("agentkernel.api.http.AKConfig")  # Mock AKConfig to avoid loading real configuration files
    @patch("agentkernel.api.http.uvicorn.run")
    def test_custom_router_integration(self, mock_uvicorn, mock_config_class):
        """Test custom router integration with prefix."""
        # Setup mock configuration
        mock_config = Mock()
        mock_config.api.custom_router_prefix = "/custom"
        mock_config.a2a.enabled = False
        mock_config.mcp.enabled = False
        mock_config_class.get.return_value = mock_config

        # Create custom router
        custom_router = APIRouter()

        @custom_router.get("/test")
        def custom_test():
            return {"message": "custom test"}

        # Add custom router
        RESTAPI._custom_routers.clear()
        RESTAPI.add(custom_router)

        # Run the RESTAPI (this won't start server due to mock)
        RESTAPI.run()

        # Verify uvicorn.run was called
        mock_uvicorn.assert_called_once()

        # Get the app that was passed to uvicorn.run
        app = mock_uvicorn.call_args[1]["app"]

        # Test the routes
        route_paths = [route.path for route in app.routes]
        assert "/health" in route_paths
        assert "/custom/test" in route_paths
        assert "/test" not in route_paths

    def test_logging_configuration(self):
        """Test that logging is properly configured."""
        # This test ensures the logging setup doesn't crash
        # The actual logging configuration is done at module level
        import logging

        logger = logging.getLogger("ak.api.http")
        assert logger is not None

    @patch("agentkernel.api.http.AKConfig")
    def test_error_handling_in_run(self, mock_config_class):
        """Test error handling in run method."""
        mock_config = Mock()
        mock_config.api.host = "localhost"
        mock_config.api.port = 8000
        mock_config.api.custom_router_prefix = "/custom"  # Ensure proper prefix
        mock_config.a2a.enabled = False
        mock_config.mcp.enabled = False
        mock_config_class.get.return_value = mock_config

        # Test with None handler (should be skipped)
        with patch("uvicorn.run") as mock_uvicorn:
            RESTAPI.run([None])
            mock_uvicorn.assert_called_once()
