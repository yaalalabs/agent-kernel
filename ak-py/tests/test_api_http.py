from unittest.mock import Mock, patch

import pytest
from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from test_secret_manager import _DictSecretProvider

from agentkernel.api.handler import RESTRequestHandler
from agentkernel.api.http import RESTAPI
from agentkernel.core.config import _IdentityConfig, _IdentityProviderConfig, _StaticPrincipalConfig, _StaticProviderConfig
from agentkernel.core.util.factory import AKConfigError
from agentkernel.identity import IdentityProviderFactory
from agentkernel.pipeline.transport.base import QueueTransportFactory
from agentkernel.secret import SecretManager


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

        # #495: with an in_memory transport a bare RESTAPI.run() boots the pipeline instead
        # (see TestPipelineDelegation); pin a broker transport to exercise the inline default path.
        with (
            patch("agentkernel.pipeline.transport.base.QueueTransportFactory.resolve_type", return_value="sqs"),
            patch("uvicorn.run") as mock_uvicorn,
        ):
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


class TestRESTAPIIntegration:
    """Integration tests for RESTAPI functionality."""

    @patch("agentkernel.api.http.AKConfig")
    def test_full_app_creation(self, mock_config_class):
        """Test full app creation."""
        mock_config = Mock()
        mock_config.api.host = "localhost"
        mock_config.api.port = 8000
        mock_config.api.custom_router_prefix = "/custom"
        mock_config.a2a.enabled = False
        mock_config.mcp.enabled = False
        mock_config_class.get.return_value = mock_config

        app = RESTAPI._create_app([])

        assert isinstance(app, FastAPI)
        route_paths = [route.path for route in app.routes if hasattr(route, "path")]
        assert "/health" in route_paths

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

        # Run the RESTAPI (this won't start server due to mock).
        # #495: pin a broker transport so the bare run() exercises the inline default path
        # rather than delegating to the pipeline IOHandler (see TestPipelineDelegation).
        with patch("agentkernel.pipeline.transport.base.QueueTransportFactory.resolve_type", return_value="sqs"):
            RESTAPI.run()

        # Verify uvicorn.run was called
        mock_uvicorn.assert_called_once()

        # Get the app that was passed to uvicorn.run
        app = mock_uvicorn.call_args[1]["app"]

        # Test the routes — Starlette 1.3+ uses _IncludedRouter objects for
        # routers added after app construction, so collect paths from both
        # direct routes and included routers.
        def collect_paths(routes, prefix=""):
            paths = []
            for route in routes:
                if hasattr(route, "path"):
                    paths.append(prefix + route.path)
                elif hasattr(route, "include_context") and hasattr(route, "original_router"):
                    ctx_prefix = getattr(route.include_context, "prefix", "")
                    paths.extend(collect_paths(route.original_router.routes, prefix + ctx_prefix))
            return paths

        route_paths = collect_paths(app.routes)
        assert "/health" in route_paths
        client = TestClient(app)
        response = client.get("/custom/test")
        assert response.status_code == 200
        assert response.json() == {"message": "custom test"}
        assert client.get("/test").status_code == 404

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


class TestResponseBuilderStructuredResult:
    """ResponseBuilder's one gate: the object form is reached only by a reply carrying a media type.

    The unlabelled assertions below are the back-compat guarantee — they must keep passing
    byte-for-byte, because no adapter sets a media type and nothing else in the framework does.
    """

    def test_structured_result_serialized_as_json_string(self):
        import json

        from agentkernel.core.chat_service import ResponseBuilder
        from agentkernel.core.model import AgentReplyAny

        content = {"city": "Colombo", "temp_c": 31}
        response = ResponseBuilder.build_response(200, "session-1", rest_api_mode=True, result=AgentReplyAny(content=content))

        assert response["result"] == json.dumps(content)
        assert response["session_id"] == "session-1"

    def test_text_result_unchanged(self):
        from agentkernel.core.chat_service import ResponseBuilder
        from agentkernel.core.model import AgentReplyText

        response = ResponseBuilder.build_response(200, "session-1", rest_api_mode=True, result=AgentReplyText(response="hello"))

        assert response["result"] == "hello"

    def test_labelled_structured_result_carries_the_object(self):
        from agentkernel.core.chat_service import ResponseBuilder
        from agentkernel.core.model import AgentReplyAny

        content = {"version": "v1.0", "createSurface": {"surfaceId": "s1"}}
        reply = AgentReplyAny(content=content, media_type="application/a2ui+json")

        response = ResponseBuilder.build_response(200, "session-1", rest_api_mode=True, result=reply)

        assert response["result"] == content
        assert response["media_type"] == "application/a2ui+json"
        assert response["session_id"] == "session-1"

    def test_labelled_list_content_carries_the_array(self):
        from agentkernel.core.chat_service import ResponseBuilder
        from agentkernel.core.model import AgentReplyAny

        content = [{"createSurface": {"surfaceId": "s1"}}, {"updateComponents": {}}]
        reply = AgentReplyAny(content=content, media_type="application/a2ui+json")

        response = ResponseBuilder.build_response(200, "session-1", rest_api_mode=True, result=reply)

        assert response["result"] == content

    def test_unlabelled_replies_never_carry_a_media_type(self):
        """The gate, from the other side: nothing without a media type gains the key."""
        from agentkernel.core.chat_service import ResponseBuilder
        from agentkernel.core.model import AgentReplyAny, AgentReplyImage, AgentReplyText

        unlabelled = [
            AgentReplyAny(content={"a": 1}),
            AgentReplyText(response="hello"),
            AgentReplyImage(response="here", image_data="x", name="i.png", mime_type="image/png"),
            object(),
        ]

        for result in unlabelled:
            response = ResponseBuilder.build_response(200, "session-1", rest_api_mode=True, result=result)
            assert "media_type" not in response
            assert isinstance(response["result"], str)

    def test_non_reply_result_keeps_its_fallback(self):
        from agentkernel.core.chat_service import ResponseBuilder

        response = ResponseBuilder.build_response(200, "session-1", rest_api_mode=True, result=object())

        assert response["result"] == "Non textual result received"


class TestPipelineDelegation:
    """RESTAPI.run() boots the single-process pipeline only for plain RESTAPI + no handlers + in_memory."""

    def test_run_delegates_to_io_handler_when_unconfigured(self, monkeypatch):
        from agentkernel.pipeline.io_handler import IOHandler
        from agentkernel.pipeline.transport.base import QueueTransportFactory

        called = {}
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "in_memory"))
        monkeypatch.setattr(IOHandler, "run", classmethod(lambda cls: called.setdefault("delegated", True)))

        with patch("agentkernel.api.http.uvicorn.run") as mock_uvicorn:
            RESTAPI.run()

        assert called.get("delegated") is True
        mock_uvicorn.assert_not_called()

    def test_run_with_explicit_handlers_does_not_delegate(self, monkeypatch):
        from agentkernel.pipeline.io_handler import IOHandler
        from agentkernel.pipeline.transport.base import QueueTransportFactory

        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "in_memory"))
        monkeypatch.setattr(IOHandler, "run", classmethod(lambda cls: pytest.fail("must not delegate")))

        handler = Mock()
        handler.get_router.return_value = APIRouter()
        with patch("agentkernel.api.http.uvicorn.run") as mock_uvicorn:
            RESTAPI.run(handlers=[handler])
        mock_uvicorn.assert_called_once()

    def test_subclass_run_does_not_delegate(self, monkeypatch):
        from agentkernel.pipeline.io_handler import IOHandler
        from agentkernel.pipeline.transport.base import QueueTransportFactory

        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "in_memory"))
        monkeypatch.setattr(IOHandler, "run", classmethod(lambda cls: pytest.fail("must not delegate")))

        handler = Mock()
        handler.get_router.return_value = APIRouter()

        class _SubAPI(RESTAPI):
            @classmethod
            def get_default_handlers(cls):
                return [handler]

        with patch("agentkernel.api.http.uvicorn.run") as mock_uvicorn:
            _SubAPI.run()
        mock_uvicorn.assert_called_once()

    def test_run_does_not_delegate_when_transport_is_not_in_memory(self, monkeypatch):
        from agentkernel.pipeline.io_handler import IOHandler
        from agentkernel.pipeline.transport.base import QueueTransportFactory

        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "sqs"))
        monkeypatch.setattr(IOHandler, "run", classmethod(lambda cls: pytest.fail("must not delegate")))

        handler = Mock()
        handler.get_router.return_value = APIRouter()
        monkeypatch.setattr(RESTAPI, "get_default_handlers", classmethod(lambda cls: [handler]))

        with patch("agentkernel.api.http.uvicorn.run") as mock_uvicorn:
            RESTAPI.run()
        mock_uvicorn.assert_called_once()


class TestPipelineOnlyHandlerRefusal:
    """A queue producer served by RESTAPI.run would enqueue into a queue no runner drains.

    The check sits outside the `cls is RESTAPI` delegation guard, so a subclass is covered too —
    `AWSRestAPI` and `AWSWebsocketAPI` inherit `run` and would otherwise serve one silently.
    """

    @staticmethod
    def _pipeline_handler(name="WebhookRESTRequestHandler"):
        handler = type(name, (RESTRequestHandler,), {"requires_pipeline": True, "get_router": lambda self: APIRouter()})
        return handler()

    def test_restapi_run_refuses_a_pipeline_only_handler(self, monkeypatch):
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "in_memory"))

        with pytest.raises(AKConfigError) as excinfo:
            RESTAPI.run(handlers=[self._pipeline_handler()])

        message = str(excinfo.value)
        assert "WebhookRESTRequestHandler" in message
        assert "IOHandler.run" in message

    def test_a_subclass_run_refuses_it_too(self, monkeypatch):
        """AWSRestAPI and AWSWebsocketAPI never reach the delegation guard, only this one."""
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "sqs"))
        offender = self._pipeline_handler()

        class _SubAPI(RESTAPI):
            @classmethod
            def get_default_handlers(cls):
                return [offender]

        with patch("agentkernel.api.http.uvicorn.run") as mock_uvicorn:
            with pytest.raises(AKConfigError, match="WebhookRESTRequestHandler"):
                _SubAPI.run()
        mock_uvicorn.assert_not_called()

    def test_the_pipeline_request_handler_is_refused_as_well(self, monkeypatch):
        """RequestHandler declares requires_pipeline for the same reason: it is a queue producer."""
        from agentkernel.pipeline.request_handler import RequestHandler

        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "sqs"))

        with pytest.raises(AKConfigError, match="RequestHandler"):
            RESTAPI.run(handlers=[RequestHandler()])

    def test_an_ordinary_handler_is_served(self, monkeypatch):
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "sqs"))
        handler = Mock()
        handler.get_router.return_value = APIRouter()
        handler.requires_pipeline = False

        with patch("agentkernel.api.http.uvicorn.run") as mock_uvicorn:
            RESTAPI.run(handlers=[handler])
        mock_uvicorn.assert_called_once()


class TestUnqueuedProtocolRefusal:
    """A2A and agent MCP run agents on the pipeline's runner (#780): every entry point that starts no
    runner refuses them at startup instead of letting each call wait out its budget."""

    @staticmethod
    def _config(a2a=False, mcp=False, expose_agents=False) -> Mock:
        config = Mock()
        config.api.host = "localhost"
        config.api.port = 8000
        config.a2a.enabled = a2a
        config.mcp.enabled = mcp
        config.mcp.expose_agents = expose_agents
        return config

    @staticmethod
    def _handler() -> Mock:
        handler = Mock()
        handler.get_router.return_value = APIRouter()
        handler.requires_pipeline = False
        return handler

    @pytest.mark.parametrize(
        "flags, surfaces",
        [
            ({}, []),
            ({"a2a": True}, ["A2A"]),
            ({"mcp": True}, []),
            ({"mcp": True, "expose_agents": True}, ["MCP"]),
            ({"expose_agents": True}, []),
            ({"a2a": True, "mcp": True, "expose_agents": True}, ["A2A", "MCP"]),
        ],
    )
    def test_agent_protocol_surfaces(self, flags, surfaces):
        assert RESTAPI.agent_protocol_surfaces(self._config(**flags)) == surfaces

    @pytest.mark.parametrize("flags, named", [({"a2a": True}, "A2A"), ({"mcp": True, "expose_agents": True}, "MCP")])
    def test_explicit_handlers_are_refused(self, monkeypatch, flags, named):
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "in_memory"))

        with patch("agentkernel.api.http.AKConfig") as config_class, patch("agentkernel.api.http.uvicorn.run") as mock_uvicorn:
            config_class.get.return_value = self._config(**flags)
            with pytest.raises(AKConfigError) as excinfo:
                RESTAPI.run(handlers=[self._handler()])

        assert named in str(excinfo.value)
        assert "IOHandler.run(handlers=[...])" in str(excinfo.value)
        mock_uvicorn.assert_not_called()

    def test_a_broker_transport_is_refused(self, monkeypatch):
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "sqs"))
        monkeypatch.setattr(RESTAPI, "get_default_handlers", classmethod(lambda cls: [self._handler()]))

        with patch("agentkernel.api.http.AKConfig") as config_class, patch("agentkernel.api.http.uvicorn.run") as mock_uvicorn:
            config_class.get.return_value = self._config(a2a=True)
            with pytest.raises(AKConfigError, match="A2A"):
                RESTAPI.run()

        mock_uvicorn.assert_not_called()

    def test_a_subclass_is_refused(self, monkeypatch):
        """AWSRestAPI and AWSWebsocketAPI inherit run and never reach the in_memory hand-off."""
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "in_memory"))
        handler = self._handler()

        class _SubAPI(RESTAPI):
            @classmethod
            def get_default_handlers(cls):
                return [handler]

        with patch("agentkernel.api.http.AKConfig") as config_class, patch("agentkernel.api.http.uvicorn.run") as mock_uvicorn:
            config_class.get.return_value = self._config(a2a=True)
            with pytest.raises(AKConfigError, match="A2A"):
                _SubAPI.run()

        mock_uvicorn.assert_not_called()

    def test_mcp_serving_only_app_tools_is_still_served(self, monkeypatch):
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "sqs"))
        monkeypatch.setattr(RESTAPI, "build_app", classmethod(lambda cls, handlers=None: "app"))

        with patch("agentkernel.api.http.AKConfig") as config_class, patch("agentkernel.api.http.uvicorn.run") as mock_uvicorn:
            config_class.get.return_value = self._config(mcp=True)
            RESTAPI.run(handlers=[self._handler()])

        assert mock_uvicorn.call_args.kwargs["app"] == "app"

    def test_a_plain_run_on_in_memory_still_hands_off_to_the_pipeline(self, monkeypatch):
        from agentkernel.pipeline.io_handler import IOHandler

        called = {}
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "in_memory"))
        monkeypatch.setattr(IOHandler, "run", classmethod(lambda cls: called.setdefault("delegated", True)))

        with patch("agentkernel.api.http.AKConfig") as config_class, patch("agentkernel.api.http.uvicorn.run") as mock_uvicorn:
            config_class.get.return_value = self._config(a2a=True, mcp=True, expose_agents=True)
            RESTAPI.run()

        assert called == {"delegated": True}
        mock_uvicorn.assert_not_called()


class _WhoAmIHandler(RESTRequestHandler):
    """A handler whose one route reports the principal the identity dependency put on the request."""

    def get_router(self) -> APIRouter:
        router = APIRouter()

        async def whoami(request: Request):
            principal = request.state.principal
            return {"subject": principal.subject, "provider": principal.provider}

        router.add_api_route("/api/v1/whoami", whoami, methods=["GET"])
        return router


class TestIdentityDependency:
    """RESTAPI installs the identity dependency on every router it includes (#603): with no identity
    block it sets the anonymous principal, with one it authenticates the bearer token."""

    @pytest.fixture
    def config(self):
        class _Cfg:
            class api:
                host = "localhost"
                port = 8000
                custom_router_prefix = "/custom"

            class a2a:
                enabled = False

            class mcp:
                enabled = False

            identity = None

        return _Cfg

    @pytest.fixture
    def mounted(self, monkeypatch, config):
        """Patch both config references and build the app around the probe handler."""
        monkeypatch.setattr("agentkernel.api.http.AKConfig.get", classmethod(lambda cls: config))
        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: config))
        IdentityProviderFactory.reset()
        yield lambda: TestClient(RESTAPI.build_app([_WhoAmIHandler()]))
        IdentityProviderFactory.reset()

    @pytest.fixture
    def static_identity(self, monkeypatch, config):
        monkeypatch.delenv("ALICE_TOKEN", raising=False)
        secrets = _DictSecretProvider()
        secrets.seed("ALICE_TOKEN", "alice-secret")
        monkeypatch.setattr(SecretManager, "current", classmethod(lambda cls: SecretManager(provider=secrets, cache_ttl=0)))
        principals = {"ALICE_TOKEN": _StaticPrincipalConfig(subject="alice", groups=["ops"])}
        config.identity = _IdentityConfig(provider=_IdentityProviderConfig(type="static", static=_StaticProviderConfig(principals=principals)))

    def test_the_dependency_is_installed_even_without_an_identity_block(self, mounted):
        client = mounted()
        assert client.get("/api/v1/whoami").json() == {"subject": "anonymous", "provider": "anonymous"}
        assert client.get("/api/v1/whoami", headers={"Authorization": "Bearer anything"}).json()["provider"] == "anonymous"

    def test_a_bearer_token_authenticates_through_the_configured_provider(self, mounted, static_identity):
        client = mounted()
        assert client.get("/api/v1/whoami", headers={"Authorization": "Bearer alice-secret"}).json() == {"subject": "alice", "provider": "static"}
        assert client.get("/api/v1/whoami").json()["provider"] == "anonymous"
        assert client.get("/api/v1/whoami", headers={"Authorization": "Bearer mallory"}).status_code == 401

    def test_custom_routers_get_the_dependency_too(self, mounted, static_identity):
        router = APIRouter()

        async def mine(request: Request):
            return {"subject": request.state.principal.subject}

        router.add_api_route("/mine", mine, methods=["GET"])
        RESTAPI._custom_routers.clear()
        RESTAPI.add(router)
        try:
            client = mounted()
            assert client.get("/custom/mine", headers={"Authorization": "Bearer alice-secret"}).json() == {"subject": "alice"}
        finally:
            RESTAPI._custom_routers.clear()

    def test_health_stays_outside(self, mounted, static_identity):
        assert mounted().get("/health", headers={"Authorization": "Bearer mallory"}).status_code == 200

    def test_the_router_dependency_list_is_the_identity_dependency_alone(self, mounted, static_identity):
        """Nothing runs ahead of the identity dependency since ``agentkernel.auth`` went (plan iteration 11)."""
        dependencies = RESTAPI._get_router_dependencies()

        assert len(dependencies) == 1
        assert dependencies[0].dependency.__name__ == "identity_dependency"
