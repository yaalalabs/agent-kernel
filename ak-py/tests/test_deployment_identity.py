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
from agentkernel.deployment.aws.core.websocket_service import AWSWebSocketHandler, WebSocketConnectionStore
from agentkernel.deployment.aws.serverless.akauthorizer import APIGatewayAuthorizer
from agentkernel.deployment.aws.serverless.aklambda import Lambda
from agentkernel.deployment.aws.serverless.akwsconnectionhandler import WebsocketConnectionHandler
from agentkernel.deployment.aws.serverless.core.router.rest_lambda import DefaultEndpointsHandler
from agentkernel.deployment.aws.serverless.core.router.ws_lambda import ConnectionRoutesHandler, SystemRoutesHandler, WSLambdaRouter
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

    @pytest.mark.parametrize("frame", [{"route": "custom_handler", "data": "your data"}, {"route": "custom_handler"}, {"any": ["shape"]}])
    def test_a_custom_route_frame_is_the_routes_own_payload(self, static_identity, frame):
        """The router picks the route from ``routeKey`` and hands the route the raw event: the frame is not a
        chat request, so ``{"route": ..., "data": ...}`` (the documented shape) must not fail chat validation."""
        from agentkernel.deployment.aws.serverless.aklambda import Lambda

        with patch(f"{WS_LAMBDA_MODULE}.WebSocketConnectionStore"):
            router = WSLambdaRouter(system_routes=False)
        router._base_route_handler.get_principal = MagicMock(return_value=ALICE)
        router._base_route_handler.broadcast = MagicMock()
        seen = []

        @router.register("custom_handler")
        def custom_handler(event, context):
            seen.append((Lambda.principal(event), json.loads(event["body"])))
            return {"response": "Custom route response"}

        event = _ws_event(body=frame)
        event["requestContext"]["routeKey"] = "custom_handler"
        with patch(f"{WS_LAMBDA_MODULE}.LambdaWSHandler.construct_endpoint_url", return_value="https://example/prod"):
            status, _ = router.dispatch(event, None)

        assert status == 200
        assert seen == [(ALICE, frame)]
        router._base_route_handler.broadcast.assert_called_once()

    def test_a_custom_route_on_a_connection_without_a_principal_is_refused(self, static_identity):
        with patch(f"{WS_LAMBDA_MODULE}.WebSocketConnectionStore"):
            router = WSLambdaRouter(system_routes=False)
        router._base_route_handler.get_principal = MagicMock(return_value=None)
        router._base_route_handler.broadcast = MagicMock()
        handler = MagicMock(return_value={"response": "never"})

        status, _ = router._get_ws_handler_function(handler)(_ws_event(body={"route": "custom_handler", "data": "x"}), None)

        assert status == 500
        handler.assert_not_called()


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


class TestEntryPointsNameTheSurface:
    """Each deployment entry point that assigns the principal to a chat body also says the request entered by the
    REST API (#603, design refinement 13), so the process that runs the agent serves only the agents on `rest`."""

    def test_the_rest_lambda_router_marks_the_body(self, static_identity):
        request = _endpoints_handler()._parse_body(_rest_event(None))

        assert request.body.surface == "rest"

    def test_the_rest_lambda_direct_route_runs_it_as_a_rest_request(self, static_identity):
        handler = _endpoints_handler()
        handler._chat_service.process_chat_request.return_value = (200, {"ok": True})

        handler._handle_agent_chat(_rest_event(None), None)

        assert handler._chat_service.process_chat_request.call_args.args[0].surface == "rest"

    def test_the_rest_lambda_queued_body_carries_it(self, static_identity):
        handler = _endpoints_handler()
        request = handler._parse_body(_rest_event(None, body={**CHAT_BODY, "request_id": "r1"}))

        with patch(f"{REST_LAMBDA_MODULE}.SQSHandler.send_message_to_input_queue", return_value={}) as send:
            handler._send_to_queue(request)

        assert send.call_args.kwargs["message_body"]["surface"] == "rest"

    def test_a_surface_the_client_put_in_a_lambda_body_is_refused(self, static_identity):
        handler = _endpoints_handler()

        response = handler._handle_agent_chat(_rest_event(None, body={**CHAT_BODY, "surface": "a2a"}), None)

        assert response["statusCode"] == 400
        assert "surface" in response["body"]
        handler._chat_service.process_chat_request.assert_not_called()

    def test_a_lambda_websocket_frame_is_marked(self, static_identity):
        info = _system_routes_handler()._parse_event_to_wsmessage(_ws_event(body={"request_id": "r1", "body": CHAT_BODY}))

        assert info.request.body.surface == "rest"

    @pytest.mark.asyncio
    async def test_an_ecs_queued_chat_frame_carries_it(self, static_identity, config):
        config.execution.queues.input.url = "https://sqs.test/input"
        handler, _ = _app_handler()

        with patch(f"{ECS_MODULE}.SQSHandler") as sqs:
            await handler._handle_chat(_ecs_request(body={"request_id": "r1", "body": CHAT_BODY}))

        assert sqs.send_message_to_input_queue.call_args.kwargs["message_body"]["surface"] == "rest"

    @pytest.mark.asyncio
    async def test_an_ecs_direct_chat_frame_runs_as_a_rest_request(self, static_identity):
        handler, _ = _app_handler()
        chat = MagicMock()
        chat.process_async_chat_request = AsyncMock(return_value=(200, {"ok": True}))
        handler.get_chat_service = lambda: chat

        await handler._handle_chat(_ecs_request(body={"request_id": "r1", "body": CHAT_BODY}))

        assert chat.process_async_chat_request.call_args.args[0].surface == "rest"


# --- credentials on the AWS deployments (#603, iteration 25b) ---------------------------------------


@pytest.fixture
def credentials_on_aws(config, monkeypatch):
    """A shared-store credentials block in the deployment configuration, over an in-process store the test can read."""
    from agentkernel.core.config import _CredentialsConfig
    from agentkernel.identity.credential.in_memory import InMemoryCredentialStore
    from agentkernel.identity.credential.manager import CredentialManager

    config.identity = SimpleNamespace(credentials=_CredentialsConfig(store={"type": "redis", "redis": {}}, encryption_key="AK_CREDENTIAL_KEY"))
    store = InMemoryCredentialStore(None)
    store.clear()
    manager = CredentialManager(store, {}, 300)
    monkeypatch.setattr(CredentialManager, "get", classmethod(lambda cls: manager))
    yield manager
    store.clear()


def _rest_event_with_header(policy_context: dict, header_name: str = "Authorization", body: dict | None = None) -> dict:
    event = _rest_event(policy_context, body=body)
    event["headers"] = {header_name: "Bearer alice-secret"}
    return event


class TestTheLambdaRESTRouterKeepsTheRequestsCredential:
    """Kept where a run starts, from the request's own header: never by the authorizer, whose cached result many
    requests share."""

    def test_the_authorizer_keeps_nothing(self, static_identity, credentials_on_aws):
        policy = APIGatewayAuthorizer().handle(_authorizer_event("Bearer alice-secret"))

        assert Principal.model_validate_json(policy["context"]["principal"]).credential_ref is None
        assert credentials_on_aws.store._entries == {}

    @pytest.mark.parametrize("header_name", ["Authorization", "authorization"])
    def test_the_queued_body_carries_a_reference_to_the_requests_credential(self, static_identity, credentials_on_aws, header_name):
        handler = _endpoints_handler()
        policy = APIGatewayAuthorizer().handle(_authorizer_event("Bearer alice-secret"))
        request = handler._parse_body(_rest_event_with_header(policy["context"], header_name, body={**CHAT_BODY, "request_id": "r1"}))

        with patch(f"{REST_LAMBDA_MODULE}.SQSHandler.send_message_to_input_queue", return_value={}) as send:
            handler._send_to_queue(request, _rest_event_with_header(policy["context"], header_name))

        sent = send.call_args.kwargs["message_body"]
        assert "alice-secret" not in json.dumps(sent)
        assert credentials_on_aws.store.get(sent["principal"]["credential_ref"]) == b"alice-secret"

    @pytest.mark.parametrize("route", ["_handle_rest_sync", "_handle_async_submit"])
    def test_each_queued_route_keeps_the_credential_of_the_request_it_sends(self, static_identity, credentials_on_aws, route):
        handler = _endpoints_handler()
        handler._get_record = MagicMock(return_value={"status_code": 200, "body": {"result": "ok"}})
        policy = APIGatewayAuthorizer().handle(_authorizer_event("Bearer alice-secret"))

        with patch(f"{REST_LAMBDA_MODULE}.SQSHandler.send_message_to_input_queue", return_value={}) as send:
            getattr(handler, route)(_rest_event_with_header(policy["context"], body={**CHAT_BODY, "request_id": "r1"}), None)

        ref = send.call_args.kwargs["message_body"]["principal"]["credential_ref"]
        assert credentials_on_aws.store.get(ref) == b"alice-secret"

    def test_the_direct_chat_route_runs_with_the_requests_credential(self, static_identity, credentials_on_aws):
        handler = _endpoints_handler()
        seen = []
        handler._chat_service.process_chat_request.side_effect = lambda body: seen.append(
            credentials_on_aws.store.get(body.principal.credential_ref)
        ) or (200, {})
        policy = APIGatewayAuthorizer().handle(_authorizer_event("Bearer alice-secret"))

        handler._handle_agent_chat(_rest_event_with_header(policy["context"]), None)

        assert seen == [b"alice-secret"]

    def test_parsing_a_request_keeps_nothing(self, static_identity, credentials_on_aws):
        # A poll for a reply parses the request too and runs nothing.
        policy = APIGatewayAuthorizer().handle(_authorizer_event("Bearer alice-secret"))

        request = _endpoints_handler()._parse_body(_rest_event_with_header(policy["context"]))

        assert request.body.principal.credential_ref is None
        assert credentials_on_aws.store._entries == {}

    def test_an_anonymous_request_keeps_nothing(self, static_identity, credentials_on_aws):
        handler = _endpoints_handler()
        request = handler._parse_body(_rest_event(None, body={**CHAT_BODY, "request_id": "r1"}))

        with patch(f"{REST_LAMBDA_MODULE}.SQSHandler.send_message_to_input_queue", return_value={}) as send:
            handler._send_to_queue(request, _rest_event(None))

        assert "credential_ref" not in send.call_args.kwargs["message_body"]["principal"]

    def test_a_queued_router_refuses_an_in_memory_store(self, static_identity, config, monkeypatch):
        from agentkernel.core.config import _CredentialsConfig

        config.identity = SimpleNamespace(credentials=_CredentialsConfig())
        handler = _endpoints_handler()
        config.execution.response_store = SimpleNamespace(type="redis")  # only its presence is read here

        with patch(f"{REST_LAMBDA_MODULE}.SQSHandler.get_input_queue_url", return_value="https://sqs.test/input"):
            with pytest.raises(AKConfigError, match="identity.credentials.store.type in_memory cannot work"):
                handler.get_routes()


class TestTheLambdaWebSocketKeepsTheConnectionsCredential:
    def test_connect_keeps_the_credential_for_the_connection(self, static_identity, credentials_on_aws):
        handler = _connection_handler()

        handler._handle_connect(_ws_event(token="alice-secret"))

        principal = handler.on_connect.call_args.kwargs["principal"]
        assert principal.credential_ref.startswith("conn:")
        assert credentials_on_aws.store.get(principal.credential_ref) == b"alice-secret"

    def test_the_connection_routes_refuse_an_in_memory_store(self, static_identity, config):
        from agentkernel.core.config import _CredentialsConfig

        config.identity = SimpleNamespace(credentials=_CredentialsConfig())

        with patch(f"{WS_LAMBDA_MODULE}.WebSocketConnectionStore"), pytest.raises(AKConfigError, match="in_memory cannot work"):
            ConnectionRoutesHandler()

    def test_every_frame_renews_the_connections_credential(self, static_identity, credentials_on_aws, monkeypatch):
        from agentkernel.identity.credential.manager import CredentialManager

        renewed = []
        monkeypatch.setattr(CredentialManager, "renew_for", classmethod(lambda cls, principal: renewed.append(principal)))

        _system_routes_handler()._parse_event_to_wsmessage(_ws_event(body={"request_id": "r1", "body": CHAT_BODY}))

        assert renewed == [ALICE]

    def test_disconnect_forgets_the_connections_credential(self, credentials_on_aws):
        import asyncio

        principal = asyncio.run(credentials_on_aws.retain(ALICE, "alice-secret", connection=True))
        connections = MagicMock()
        connections.get_principal.return_value = principal
        handler = AWSWebSocketHandler(connection_store=connections)

        handler.on_disconnect(connection_id="c1")

        assert credentials_on_aws.store.get(principal.credential_ref) is None
        connections.delete_by_connection_id.assert_called_once_with("c1")


class TestTheECSWebSocketKeepsTheConnectionsCredential:
    @pytest.mark.asyncio
    async def test_connect_keeps_the_credential_for_the_connection(self, static_identity, credentials_on_aws):
        handler, ws = _system_handler()

        await handler._handle_connect(_ecs_request(token="alice-secret"))

        principal = ws.on_connect.call_args.kwargs["principal"]
        assert principal.credential_ref.startswith("conn:")
        assert credentials_on_aws.store.get(principal.credential_ref) == b"alice-secret"

    @pytest.mark.asyncio
    async def test_every_frame_renews_the_connections_credential(self, static_identity, credentials_on_aws, monkeypatch):
        from agentkernel.identity.credential.manager import CredentialManager

        renewed = []
        monkeypatch.setattr(CredentialManager, "renew_for", classmethod(lambda cls, principal: renewed.append(principal)))
        handler, _ = _app_handler()

        await handler.build_route_context(_ecs_request(body={"request_id": "r1", "body": CHAT_BODY}), is_chat_request=True)

        assert renewed == [ALICE]


class TestTheServerlessRunnersReleaseTheCredential:
    @staticmethod
    def _record(principal: Principal) -> dict:
        return {
            "body": json.dumps({"prompt": "hi", "session_id": "s1", "principal": principal.model_dump(mode="json")}),
            "attributes": {"MessageGroupId": "s1", "MessageDeduplicationId": "req-1"},
            "messageAttributes": {"request_id": {"stringValue": "req-1", "DataType": "String"}},
        }

    @pytest.mark.parametrize("failure", [None, RuntimeError("down")])
    def test_the_agent_runner_deletes_it_when_the_message_is_done(self, credentials_on_aws, failure):
        import asyncio

        from agentkernel.deployment.aws.serverless.akagentrunner import ServerlessAgentRunner

        principal = asyncio.run(credentials_on_aws.retain(ALICE, "alice-secret"))
        chat = MagicMock()
        chat.process_chat_request.side_effect = failure or (lambda req, requests=None: (200, {"result": "ok", "session_id": "s1"}))
        with (
            patch.object(ServerlessAgentRunner, "_get_chat_service", return_value=chat),
            patch("agentkernel.deployment.aws.serverless.akagentrunner.SQSHandler.send_message_to_output_queue"),
        ):
            try:
                ServerlessAgentRunner.process_message(self._record(principal))
            except RuntimeError:
                pass

        assert credentials_on_aws.store.get(principal.credential_ref) is None

    def test_the_stream_runner_deletes_it_too(self, credentials_on_aws):
        import asyncio

        from agentkernel.deployment.aws.serverless.akagentrunner import ServerlessStreamAgentRunner

        principal = asyncio.run(credentials_on_aws.retain(ALICE, "alice-secret"))
        chat = MagicMock()
        chat.process_stream_chat_sync.return_value = iter([])
        with (
            patch.object(ServerlessStreamAgentRunner, "_get_chat_service", return_value=chat),
            patch("agentkernel.deployment.aws.serverless.akagentrunner.SQSHandler"),
        ):
            try:
                ServerlessStreamAgentRunner.process_message(self._record(principal))
            except Exception:
                pass

        assert credentials_on_aws.store.get(principal.credential_ref) is None


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

    @pytest.mark.parametrize("name", ["ECSIOHandler", "ECSAgentRunner", "ECSOutputConsumer", "AWSRestAPI"])
    def test_the_ecs_only_pipeline_classes_are_gone(self, name):
        import agentkernel.aws as aws

        assert not hasattr(aws, name)

    def test_the_entry_points_take_no_validator(self):
        assert list(inspect.signature(AWSWebsocketAPI.run).parameters) == ["handlers"]
        assert "auth_validator" not in inspect.signature(WSLambdaRouter.__init__).parameters
        assert list(inspect.signature(APIGatewayAuthorizer.__init__).parameters) == ["self", "bypass"]
