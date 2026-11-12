"""The deployment adapters on the identity provider (#603, plan iteration 11).

The ECS and Lambda ``$connect`` handlers authenticate the ``token`` query parameter through the
configured provider and key the connection by the principal's subject; the AWS connection store
keeps the whole principal, so every later frame runs as it. The API Gateway authorizer serializes
the principal into the policy context and the REST Lambda router rebuilds it onto the body; the
Azure handler authenticates the bearer header itself. The names the ``agentkernel.auth`` package
carried stay removed.
"""

import importlib
import inspect
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import azure.functions as func
import pytest

from agentkernel.api.http import RESTAPI
from agentkernel.core.config import _ExecutionConfig
from agentkernel.core.model import ExecutionMode, Principal
from agentkernel.core.util.factory import AKConfigError
from agentkernel.deployment.aws.containerized.core.api.websocket_api import (
    AWSWebsocketAPI,
    ECSWebSocketRequestHandler,
    ECSWebSocketSystemRequestHandler,
)
from agentkernel.deployment.aws.containerized.ecs_io_handler import ECSIOHandler
from agentkernel.deployment.aws.core.websocket_service import AWSWebSocketHandler, WebSocketConnectionStore
from agentkernel.deployment.aws.serverless.akauthorizer import APIGatewayAuthorizer
from agentkernel.deployment.aws.serverless.aklambda import Lambda
from agentkernel.deployment.aws.serverless.akwsconnectionhandler import WebsocketConnectionHandler
from agentkernel.deployment.aws.serverless.core.router.rest_lambda import DefaultEndpointsHandler
from agentkernel.deployment.aws.serverless.core.router.ws_lambda import ConnectionRoutesHandler, SystemRoutesHandler, WSLambdaRouter
from agentkernel.deployment.azure.akfunction import AzureFunctions
from agentkernel.identity import IdentityProviderFactory

ALICE = Principal(subject="alice", provider="static", namespace="static", groups=["ops"])
ENDPOINT = "https://abc.execute-api.us-east-1.amazonaws.com/prod"
ECS_MODULE = "agentkernel.deployment.aws.containerized.core.api.websocket_api"
WS_LAMBDA_MODULE = "agentkernel.deployment.aws.serverless.core.router.ws_lambda"
REST_LAMBDA_MODULE = "agentkernel.deployment.aws.serverless.core.router.rest_lambda"
WS_SERVICE_MODULE = "agentkernel.deployment.aws.core.websocket_service"
CHAT_BODY = {"prompt": "hi", "session_id": "s1"}
FORGED = {"subject": "mallory", "provider": "static", "namespace": "static"}


@pytest.fixture(autouse=True)
def config(monkeypatch):
    """What the deployment handlers read from configuration: a connection table, a chat route, an execution mode."""
    cfg = SimpleNamespace(
        websocket_api=SimpleNamespace(
            endpoint_url=ENDPOINT, connection_table=SimpleNamespace(table_name="ak-connections", ttl=3600), chat_route="chat"
        ),
        execution=_ExecutionConfig(mode=ExecutionMode.ASYNC),
        identity=None,
    )
    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: cfg))
    return cfg


@pytest.fixture
def no_identity(monkeypatch):
    monkeypatch.setattr(IdentityProviderFactory, "get", classmethod(lambda cls: None))


def _effect(policy: dict) -> str:
    return policy["policyDocument"]["Statement"][0]["Effect"]


def _authorizer_event(authorization: str | None, path: str = "/api/v1/chat") -> dict:
    headers = {"Content-Type": "application/json"}
    if authorization is not None:
        headers["Authorization"] = authorization
    return {
        "type": "REQUEST",
        "methodArn": f"arn:aws:execute-api:us-east-1:123456789012:abc/prod/POST{path}",
        "path": path,
        "httpMethod": "POST",
        "headers": headers,
    }


def _rest_event(policy_context: dict | None, body: dict | None = None) -> dict:
    event = {"httpMethod": "POST", "path": "/api/v1/chat", "body": json.dumps(body if body is not None else CHAT_BODY)}
    if policy_context is not None:
        event["requestContext"] = {"authorizer": policy_context}
    return event


def _endpoints_handler() -> DefaultEndpointsHandler:
    with patch(f"{REST_LAMBDA_MODULE}.ChatService"):
        return DefaultEndpointsHandler()


class TestAuthorizerToRESTRouter:
    """The authorizer puts the principal in the policy context as JSON; the REST Lambda router rebuilds it onto the body."""

    def test_the_policy_names_the_subject_and_carries_the_serialized_principal(self, static_identity):
        policy = APIGatewayAuthorizer().handle(_authorizer_event("Bearer alice-secret"))

        assert (_effect(policy), policy["principalId"]) == ("Allow", "alice")
        assert Principal.model_validate_json(policy["context"]["principal"]) == ALICE

    def test_the_router_rebuilds_the_principal_from_the_authorizer_context(self, static_identity):
        policy = APIGatewayAuthorizer().handle(_authorizer_event("Bearer alice-secret"))

        request = _endpoints_handler()._parse_body(_rest_event(policy["context"]))

        assert request.body.principal == ALICE

    def test_without_an_authorizer_context_the_body_runs_anonymously(self, static_identity):
        request = _endpoints_handler()._parse_body(_rest_event(None))

        assert request.body.principal is not None and request.body.principal.is_anonymous

    def test_a_principal_the_client_put_in_the_body_is_replaced(self, static_identity):
        policy = APIGatewayAuthorizer().handle(_authorizer_event("Bearer alice-secret"))

        request = _endpoints_handler()._parse_body(_rest_event(policy["context"], body={**CHAT_BODY, "principal": FORGED}))

        assert request.body.principal == ALICE

    def test_the_direct_chat_route_runs_as_the_principal(self, static_identity):
        handler = _endpoints_handler()
        handler._chat_service.process_chat_request.return_value = (200, {"ok": True})
        policy = APIGatewayAuthorizer().handle(_authorizer_event("Bearer alice-secret"))

        response = handler._handle_agent_chat(_rest_event(policy["context"]), None)

        assert response["statusCode"] == 200
        assert handler._chat_service.process_chat_request.call_args.args[0].principal == ALICE

    def test_the_queued_body_carries_the_principal(self, static_identity):
        handler = _endpoints_handler()
        policy = APIGatewayAuthorizer().handle(_authorizer_event("Bearer alice-secret"))
        request = handler._parse_body(_rest_event(policy["context"], body={**CHAT_BODY, "request_id": "r1"}))

        with patch(f"{REST_LAMBDA_MODULE}.SQSHandler.send_message_to_input_queue", return_value={}) as send:
            handler._send_to_queue(request)

        assert send.call_args.kwargs["message_body"]["principal"]["subject"] == "alice"


class TestLambdaPrincipalAccessor:
    """A ``Lambda.register`` route receives the raw event; ``Lambda.principal`` reads the caller out of it."""

    def test_the_authorizer_context_rebuilds_the_principal(self, static_identity):
        policy = APIGatewayAuthorizer().handle(_authorizer_event("Bearer alice-secret"))

        assert Lambda.principal({"requestContext": {"authorizer": policy["context"]}}) == ALICE

    @pytest.mark.parametrize("event", [{"httpMethod": "GET"}, {"requestContext": {}}, {"requestContext": {"authorizer": {}}}])
    def test_an_event_without_an_authorizer_principal_is_anonymous(self, event):
        assert Lambda.principal(event).is_anonymous


def _ecs_request(connection_id: str | None = "c1", token: str | None = None, body: dict | None = None) -> MagicMock:
    request = MagicMock()
    request.headers = {ECSWebSocketSystemRequestHandler.CONNECTION_ID_HEADER: connection_id} if connection_id else {}
    request.query_params = {"token": token} if token is not None else {}
    request.body = AsyncMock(return_value=json.dumps(body or {}).encode())
    return request


def _system_handler() -> tuple[ECSWebSocketSystemRequestHandler, MagicMock]:
    handler = ECSWebSocketSystemRequestHandler()
    ws = MagicMock()
    handler.get_websocket_handler = lambda: ws
    return handler, ws


def _app_handler(custom_routes=None, principal: Principal | None = ALICE) -> tuple[ECSWebSocketRequestHandler, MagicMock]:
    handler = ECSWebSocketRequestHandler(custom_routes=custom_routes)
    ws = MagicMock()
    ws.get_principal.return_value = principal
    handler.get_websocket_handler = lambda: ws
    return handler, ws


class TestECSConnect:
    def test_construction_requires_an_identity_block(self, no_identity):
        with pytest.raises(AKConfigError, match="identity block"):
            ECSWebSocketSystemRequestHandler()

    def test_the_default_handlers_need_the_identity_block_too(self, no_identity):
        with pytest.raises(AKConfigError, match="identity block"):
            AWSWebsocketAPI.get_default_handlers()

    @pytest.mark.asyncio
    async def test_a_valid_token_connects_as_the_principal(self, static_identity):
        handler, ws = _system_handler()

        response = await handler._handle_connect(_ecs_request(token="alice-secret"))

        assert (response.status_code, json.loads(response.body)["user_id"]) == (200, "alice")
        ws.on_connect.assert_called_once_with(connection_id="c1", principal=ALICE)

    @pytest.mark.asyncio
    async def test_an_invalid_token_is_refused_with_a_generic_reason(self, static_identity):
        handler, ws = _system_handler()

        response = await handler._handle_connect(_ecs_request(token="mallory"))

        assert (response.status_code, json.loads(response.body)["message"]) == (401, "Authentication failed")
        ws.on_connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_missing_token_is_refused_without_consulting_the_provider(self, static_identity):
        handler, ws = _system_handler()

        response = await handler._handle_connect(_ecs_request())

        assert (response.status_code, json.loads(response.body)["message"]) == (401, "Authentication token is required")
        assert static_identity.calls == []
        ws.on_connect.assert_not_called()


class TestECSFrames:
    @pytest.mark.asyncio
    async def test_the_route_context_carries_the_connections_principal(self, static_identity):
        handler, ws = _app_handler()

        ctx = await handler.build_route_context(_ecs_request(body={"request_id": "r1", "body": CHAT_BODY}), is_chat_request=True)

        assert (ctx.principal, ctx.user_id) == (ALICE, "alice")
        ws.get_principal.assert_called_once_with("c1")

    @pytest.mark.asyncio
    async def test_a_connection_without_a_stored_principal_is_401(self, static_identity):
        handler, _ = _app_handler(principal=None)

        with pytest.raises(handler.WSRouteError) as excinfo:
            await handler.build_route_context(_ecs_request(body={}))

        assert excinfo.value.status_code == 401

    @pytest.mark.asyncio
    async def test_a_queued_chat_frame_carries_the_principal(self, static_identity, config):
        config.execution.queues.input.url = "https://sqs.test/input"
        handler, _ = _app_handler()

        with patch(f"{ECS_MODULE}.SQSHandler") as sqs:
            response = await handler._handle_chat(_ecs_request(body={"request_id": "r1", "body": {**CHAT_BODY, "principal": FORGED}}))

        assert response.status_code == 200
        sent = sqs.send_message_to_input_queue.call_args.kwargs
        assert (sent["message_body"]["principal"]["subject"], sent["user_id"]) == ("alice", "alice")

    @pytest.mark.asyncio
    async def test_a_direct_chat_frame_runs_as_the_principal(self, static_identity):
        handler, _ = _app_handler()
        chat = MagicMock()
        chat.process_async_chat_request = AsyncMock(return_value=(200, {"ok": True}))
        handler.get_chat_service = lambda: chat

        response = await handler._handle_chat(_ecs_request(body={"request_id": "r1", "body": CHAT_BODY}))

        assert response.status_code == 200
        assert chat.process_async_chat_request.call_args.args[0].principal == ALICE

    @pytest.mark.asyncio
    async def test_a_custom_route_receives_the_message_and_the_principal(self, static_identity):
        handler, _ = _app_handler()
        received = {}

        def route(ctx):
            received.update(ctx)

        await handler._wrap_custom_route(route)(request=_ecs_request(body={"foo": "bar"}))

        assert received == {"message": {"foo": "bar"}, "principal": ALICE}


def _ws_event(token: str | None = None, body: dict | None = None) -> dict:
    event = {"requestContext": {"connectionId": "conn-1", "domainName": "example.execute-api.us-east-1.amazonaws.com", "stage": "prod"}}
    if token is not None:
        event["queryStringParameters"] = {"token": token}
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def _connection_handler() -> ConnectionRoutesHandler:
    with patch(f"{WS_LAMBDA_MODULE}.WebSocketConnectionStore"):
        handler = ConnectionRoutesHandler()
    handler.on_connect = MagicMock()
    return handler


def _system_routes_handler(principal: Principal | None = ALICE) -> SystemRoutesHandler:
    with patch(f"{WS_LAMBDA_MODULE}.WebSocketConnectionStore"), patch(f"{WS_LAMBDA_MODULE}.ChatService"):
        handler = SystemRoutesHandler()
    handler.get_principal = MagicMock(return_value=principal)
    handler.broadcast = MagicMock()
    return handler


class TestLambdaConnect:
    def test_construction_requires_an_identity_block(self, no_identity):
        with patch(f"{WS_LAMBDA_MODULE}.WebSocketConnectionStore"), pytest.raises(AKConfigError, match="identity block"):
            ConnectionRoutesHandler()

    def test_the_router_builds_the_connection_routes_from_configuration_alone(self, static_identity):
        with patch(f"{WS_LAMBDA_MODULE}.WebSocketConnectionStore"):
            router = WSLambdaRouter(connection_routes=True, system_routes=False)

        assert set(router._websocket_routes) == {"$connect", "$disconnect"}

    def test_a_valid_token_connects_as_the_principal(self, static_identity):
        handler = _connection_handler()

        status, body = handler._handle_connect(_ws_event(token="alice-secret"))

        assert (status, body["user_id"]) == (200, "alice")
        handler.on_connect.assert_called_once_with(connection_id="conn-1", principal=ALICE)

    def test_an_invalid_token_is_refused_with_a_generic_reason(self, static_identity):
        handler = _connection_handler()

        status, body = handler._handle_connect(_ws_event(token="mallory"))

        assert (status, body["message"]) == (401, "Authentication failed")
        handler.on_connect.assert_not_called()

    def test_a_missing_token_is_refused_without_consulting_the_provider(self, static_identity):
        status, body = _connection_handler()._handle_connect(_ws_event())

        assert (status, body["message"]) == (401, "Authentication token is required")
        assert static_identity.calls == []


class TestLambdaFrames:
    def test_a_frame_resolves_the_connections_principal(self, static_identity):
        handler = _system_routes_handler()

        info = handler._parse_event_to_wsmessage(_ws_event(body={"request_id": "r1", "body": CHAT_BODY}))

        assert (info.user_id, info.principal) == ("alice", ALICE)
        handler.get_principal.assert_called_once_with("conn-1")

    def test_a_connection_without_a_stored_principal_is_refused(self, static_identity):
        handler = _system_routes_handler(principal=None)

        with pytest.raises(ValueError, match="No principal found for connection_id: conn-1"):
            handler._parse_event_to_wsmessage(_ws_event(body={"request_id": "r1", "body": CHAT_BODY}))

    def test_a_direct_chat_runs_as_the_principal(self, static_identity):
        handler = _system_routes_handler()
        handler._chat_service.process_chat_request.return_value = (200, {"ok": True})

        status, _ = handler._handle_direct_chat(_ws_event(body={"request_id": "r1", "body": {**CHAT_BODY, "principal": FORGED}}))

        assert status == 200
        assert handler._chat_service.process_chat_request.call_args.args[0].principal == ALICE

    def test_a_queued_chat_body_carries_the_principal(self, static_identity, config):
        config.execution.queues.input.url = "https://sqs.test/input"
        handler = _system_routes_handler()

        with patch(f"{WS_LAMBDA_MODULE}.SQSHandler") as sqs:
            sqs.CustomAttribute = MagicMock(side_effect=lambda **kwargs: kwargs)
            status, _ = handler._handle_queue_mode(_ws_event(body={"request_id": "r1", "body": CHAT_BODY}))

        assert status == 200
        sent = sqs.send_message_to_input_queue.call_args.kwargs
        assert (sent["message_body"]["principal"]["subject"], sent["user_id"]) == ("alice", "alice")


class TestLambdaCustomWebSocketRoutes:
    """WebSocket events carry no authorizer context, so a ``Lambda.register`` route reads the connection's
    principal through ``Lambda.principal(event)`` only because the router puts it there (#603 review)."""

    def test_a_custom_route_reads_the_connections_principal(self, static_identity):
        from agentkernel.deployment.aws.serverless.aklambda import Lambda

        with patch(f"{WS_LAMBDA_MODULE}.WebSocketConnectionStore"):
            router = WSLambdaRouter(system_routes=False)
        router._base_route_handler.get_principal = MagicMock(return_value=ALICE)
        router._base_route_handler.broadcast = MagicMock()
        seen = []

        def echo(event, context):
            seen.append(Lambda.principal(event))
            return {"echo": "hi"}

        with patch(f"{WS_LAMBDA_MODULE}.LambdaWSHandler.construct_endpoint_url", return_value="https://example/prod"):
            status, _ = router._get_ws_handler_function(echo)(_ws_event(body={"route": "echo"}), None)

        assert status == 200
        assert seen == [ALICE]


def _azure_request(headers: dict | None = None, body: dict | None = None) -> func.HttpRequest:
    payload = CHAT_BODY if body is None else body
    return func.HttpRequest(method="POST", url="https://fn.example.net/api/chat", headers=headers or {}, body=json.dumps(payload).encode())


class TestAzureFunctions:
    @pytest.fixture
    def chat_service(self, monkeypatch):
        service = MagicMock()
        service.process_chat_request.return_value = (200, {"ok": True})
        monkeypatch.setattr(AzureFunctions, "_chat_service", service)
        return service

    def test_a_bearer_token_runs_the_request_as_the_principal(self, static_identity, chat_service):
        response = AzureFunctions.handler(_azure_request({"Authorization": "Bearer alice-secret"}, body={**CHAT_BODY, "principal": FORGED}))

        assert response.status_code == 200
        assert chat_service.process_chat_request.call_args.args[0].principal == ALICE

    def test_an_invalid_token_is_401_before_the_body_is_read(self, static_identity, chat_service):
        """An empty body would be a 400; the credential is refused first."""
        response = AzureFunctions.handler(_azure_request({"Authorization": "Bearer mallory"}, body={}))

        assert response.status_code == 401
        assert json.loads(response.get_body()) == {"error": "Unauthorized", "session_id": None}
        chat_service.process_chat_request.assert_not_called()

    def test_a_malformed_header_is_401_with_its_own_detail(self, static_identity, chat_service):
        response = AzureFunctions.handler(_azure_request({"Authorization": "Token abc"}))

        assert (response.status_code, json.loads(response.get_body())["error"]) == (401, "Invalid authorization header")
        chat_service.process_chat_request.assert_not_called()

    def test_the_function_key_stays_out_of_the_log_and_the_context(self, static_identity, chat_service, caplog):
        """Under authLevel: function a caller may send ``?code=``; only the path is logged or handed to the provider."""
        request = func.HttpRequest(
            method="POST",
            url="https://fn.example.net/api/chat?code=the-function-key",
            headers={"Authorization": "Bearer mallory"},
            body=json.dumps(CHAT_BODY).encode(),
        )
        with caplog.at_level("INFO"):
            response = AzureFunctions.handler(request)

        assert response.status_code == 401
        assert "the-function-key" not in " ".join(record.getMessage() for record in caplog.records)
        ((_, context),) = static_identity.calls
        assert context.path == "/api/chat"

    def test_no_header_runs_anonymously(self, static_identity, chat_service):
        AzureFunctions.handler(_azure_request())

        assert chat_service.process_chat_request.call_args.args[0].principal.is_anonymous


class TestConnectionStorePrincipal:
    """The DynamoDB connection row keeps the principal beside the subject, so later frames carry groups too."""

    @pytest.fixture
    def store(self):
        table = MagicMock()
        with patch(f"{WS_SERVICE_MODULE}.boto3") as boto3:
            boto3.resource.return_value.Table.return_value = table
            yield WebSocketConnectionStore(table_name="ak-connections", ttl=60), table

    def test_connect_writes_the_principal_beside_the_subject(self, store):
        connections, table = store

        connections.add_connection("alice", "c1", ALICE)

        item = table.put_item.call_args.kwargs["Item"]
        assert (item["user_id"], item["connection_id"]) == ("alice", "c1")
        assert Principal.model_validate_json(item["principal"]) == ALICE

    def test_a_row_written_without_a_principal_keeps_the_old_shape(self, store):
        connections, table = store

        connections.add_connection("alice", "c1")

        assert "principal" not in table.put_item.call_args.kwargs["Item"]

    def test_get_principal_rebuilds_it_from_the_row(self, store):
        connections, table = store
        table.query.return_value = {"Items": [{"user_id": "alice", "connection_id": "c1", "principal": ALICE.model_dump_json()}]}

        assert connections.get_principal("c1") == ALICE
        assert table.query.call_args.kwargs["IndexName"] == "connection_id-index"

    @pytest.mark.parametrize("items", [[], [{"user_id": "alice", "connection_id": "c1"}]])
    def test_get_principal_is_none_for_an_unknown_or_legacy_row(self, store, items):
        connections, table = store
        table.query.return_value = {"Items": items}

        assert connections.get_principal("c1") is None

    def test_the_aws_handler_records_and_reads_the_principal(self, store):
        connections, table = store
        handler = AWSWebSocketHandler(connection_store=connections)

        handler.on_connect(connection_id="c1", principal=ALICE)
        table.query.return_value = {"Items": [table.put_item.call_args.kwargs["Item"]]}

        assert table.put_item.call_args.kwargs["Item"]["user_id"] == "alice"
        assert handler.get_principal("c1") == ALICE


class TestRemovedNames:
    def test_the_auth_package_is_gone(self):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("agentkernel.auth")

    def test_the_gcp_authorizer_is_gone(self):
        import agentkernel.deployment.gcp as gcp

        assert not hasattr(gcp, "GCPAuthorizer")
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("agentkernel.deployment.gcp.akauthorizer")

    def test_the_validator_registration_hooks_are_gone(self):
        assert not hasattr(AWSWebsocketAPI, "set_auth_handler")
        assert not hasattr(WebsocketConnectionHandler, "set_auth_validator")
        assert not hasattr(RESTAPI, "add_auth_handlers")
        assert not hasattr(RESTAPI, "_auth_token_validators")

    def test_the_entry_points_take_no_validator(self):
        assert list(inspect.signature(ECSIOHandler.run).parameters) == ["handlers"]
        assert "auth_validator" not in inspect.signature(WSLambdaRouter.__init__).parameters
        assert list(inspect.signature(APIGatewayAuthorizer.__init__).parameters) == ["self", "bypass"]
