"""The A2A / MCP request-Lambda host (#932): the app lifespan, the hosted paths and the host itself.

``AppLifespan`` is driven here the way ``LambdaProtocolHost`` drives its loop: one long-lived event loop that is
never made current, and a separate ``run_until_complete`` call per invocation. The host tests run the real app, the real
A2A routes and the real MCP mount, behind the host; only the queue client is faked.
"""

import asyncio
import json
import logging
import re
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastmcp import FastMCP
from starlette.exceptions import HTTPException

from agentkernel.api.a2a.a2a import A2A
from agentkernel.api.http import RESTAPI
from agentkernel.api.mcp.akmcp import MCP
from agentkernel.core.base import Agent, Runner
from agentkernel.core.chat_service import ResponseBuilder
from agentkernel.core.config import AKConfig
from agentkernel.core.model import AgentReplyText
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.util.factory import AKConfigError
from agentkernel.deployment.aws.serverless.aklambda import Lambda
from agentkernel.deployment.aws.serverless.core.event_translator import LambdaEventTranslator
from agentkernel.deployment.aws.serverless.core.protocol_host import AppLifespan, LambdaProtocolHost
from agentkernel.deployment.aws.serverless.core.protocol_paths import ProtocolPaths
from agentkernel.pipeline.request_handler import QueuedReply, ReplyTimeoutError

translator = LambdaEventTranslator()

MCP_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


def _event(path: str = "/", method: str = "GET", body: str | None = None, headers: dict | None = None) -> dict:
    return {
        "httpMethod": method,
        "path": path,
        "headers": {"Host": "abc.execute-api.us-east-1.amazonaws.com", **(headers or {})},
        "multiValueHeaders": None,
        "queryStringParameters": None,
        "multiValueQueryStringParameters": None,
        "body": body,
        "isBase64Encoded": False,
        "requestContext": {"domainName": "abc.execute-api.us-east-1.amazonaws.com"},
    }


class HostLoop:
    """What ``LambdaHost._run`` gives a host: one loop per execution environment, never made current."""

    def __init__(self):
        self._loop = asyncio.new_event_loop()

    def run(self, coroutine):
        return self._loop.run_until_complete(coroutine)

    def close(self):
        """Cancel what a test left parked (the held lifespan) so the loop closes clean."""

        async def drain():
            pending = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

        self._loop.run_until_complete(drain())
        self._loop.close()


@pytest.fixture
def host_loop():
    loop = HostLoop()
    yield loop
    loop.close()


def _app_with_lifespan(log: list[str]) -> FastAPI:
    """A FastAPI app whose lifespan records itself and flips a flag a route reads.

    ``AppLifespan`` never closes the lifespan, so ``shutdown`` must never appear in the log.
    """

    @asynccontextmanager
    async def lifespan(app):
        log.append("startup")
        app.state.open = True
        yield
        app.state.open = False
        log.append("shutdown")

    app = FastAPI(lifespan=lifespan)

    @app.get("/state")
    async def state():
        return {"open": app.state.open}

    return app


class TestAppLifespan:
    def test_start_returns_once_the_startup_has_run_and_shutdown_has_not(self, host_loop):
        log: list[str] = []

        host_loop.run(AppLifespan(_app_with_lifespan(log)).start())

        assert log == ["startup"]

    def test_the_lifespan_stays_open_across_separate_invocations(self, host_loop):
        """Three ``run_until_complete`` calls, as three warm invocations: one startup, open every time."""
        log: list[str] = []
        app = _app_with_lifespan(log)
        host_loop.run(AppLifespan(app).start())

        answers = [host_loop.run(translator.call_app(app, _event("/state"), "/state")) for _ in range(3)]

        assert [json.loads(answer["body"]) for answer in answers] == [{"open": True}] * 3
        assert log == ["startup"]

    def test_a_startup_failure_is_raised_from_start(self, host_loop):
        """A broken app fails the Lambda's init, not its first request."""

        @asynccontextmanager
        async def lifespan(app):
            raise RuntimeError("startup failed")
            yield

        with pytest.raises(RuntimeError, match="startup failed"):
            host_loop.run(AppLifespan(FastAPI(lifespan=lifespan)).start())

    def test_it_cannot_be_started_twice(self, host_loop):
        lifespan = AppLifespan(_app_with_lifespan([]))
        host_loop.run(lifespan.start())

        with pytest.raises(RuntimeError, match="already started"):
            host_loop.run(lifespan.start())


class TestFastMCPBehindAppLifespan:
    """FastMCP refuses every request until its lifespan has run; the lifespan has to outlive each invocation."""

    @staticmethod
    def _mcp_app() -> FastAPI:
        mcp = FastMCP("spike")

        @mcp.tool
        def ping() -> str:
            return "pong"

        mcp_app = mcp.http_app(path="/", stateless_http=True)
        app = FastAPI(lifespan=mcp_app.lifespan)
        app.mount("/mcp", mcp_app)
        return app

    @staticmethod
    def _tool_call(call_id: int = 1) -> dict:
        body = json.dumps({"jsonrpc": "2.0", "id": call_id, "method": "tools/call", "params": {"name": "ping", "arguments": {}}})
        return _event("/api/v1/mcp/", method="POST", body=body, headers=MCP_HEADERS)

    def test_a_request_before_the_lifespan_has_run_is_refused(self, host_loop):
        app = self._mcp_app()

        with pytest.raises(RuntimeError, match="task group"):
            host_loop.run(translator.call_app(app, self._tool_call(), "/mcp/"))

    def test_a_tool_call_after_start_gets_one_whole_event_stream_answer(self, host_loop):
        app = self._mcp_app()
        host_loop.run(AppLifespan(app).start())

        proxy = host_loop.run(translator.call_app(app, self._tool_call(), "/mcp/"))

        assert proxy["statusCode"] == 200
        assert proxy["multiValueHeaders"]["content-type"] == ["text/event-stream"]
        assert "pong" in proxy["body"]
        assert proxy["body"].startswith("event: message")

    def test_the_lifespan_serves_three_invocations_in_a_row(self, host_loop):
        app = self._mcp_app()
        host_loop.run(AppLifespan(app).start())

        answers = [host_loop.run(translator.call_app(app, self._tool_call(call_id), "/mcp/")) for call_id in (1, 2, 3)]

        assert [answer["statusCode"] for answer in answers] == [200, 200, 200]
        assert all("pong" in answer["body"] for answer in answers)

    def test_a_get_for_server_push_is_a_405(self, host_loop):
        """Stateless MCP answers a GET with 405 by itself; the host adds no code for it."""
        app = self._mcp_app()
        host_loop.run(AppLifespan(app).start())

        proxy = host_loop.run(translator.call_app(app, _event("/api/v1/mcp/", method="GET", headers=MCP_HEADERS), "/mcp/"))

        assert proxy["statusCode"] == 405


class TestProtocolPaths:
    def test_the_hosted_prefixes_are_a2a_and_mcp(self):
        assert ProtocolPaths.PREFIXES == ("/a2a", "/mcp")

    @pytest.mark.parametrize(
        "app_path",
        ["/a2a", "/a2a/catalog", "/a2a/triage/message:send", "/a2a/triage/tasks/123:cancel", "/mcp", "/mcp/", "/mcp/anything"],
    )
    def test_a_prefix_and_everything_under_it_is_hosted(self, app_path):
        assert ProtocolPaths.matches(app_path)

    @pytest.mark.parametrize("app_path", ["/", "", "/chat", "/api/v1/chat", "/a2ax", "/mcpx", "/x/a2a", "/slack/events", "a2a"])
    def test_anything_else_is_not(self, app_path):
        """A prefix has to end at a path segment: ``/a2ax`` is not ``/a2a``."""
        assert not ProtocolPaths.matches(app_path)

    def test_importing_it_loads_no_fastapi(self):
        """The authorizer reads these paths and its package carries no FastAPI."""
        code = (
            "import sys\n"
            "from agentkernel.deployment.aws.serverless.core.protocol_paths import ProtocolPaths\n"
            "assert 'fastapi' not in sys.modules and 'starlette' not in sys.modules, 'loaded fastapi or starlette'\n"
        )

        result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)

        assert result.returncode == 0, result.stderr


class TestProtocolPathRoutes:
    """``ROUTES``: the (path, method) pairs the application registers, matching the Terraform resource templates."""

    def test_the_routes_are_the_four_templates_for_get_post_and_delete(self):
        assert sorted(ProtocolPaths.ROUTES) == sorted(
            (template, method) for template in ("/a2a", "/a2a/{proxy+}", "/mcp", "/mcp/{proxy+}") for method in ("GET", "POST", "DELETE")
        )

    def test_no_route_is_listed_twice(self):
        assert len(set(ProtocolPaths.ROUTES)) == len(ProtocolPaths.ROUTES)

    def test_every_route_belongs_to_a_hosted_prefix(self):
        """``matches`` reads an app path, so a template's ``{proxy+}`` stands in for any one segment."""
        assert all(ProtocolPaths.matches(path.replace("{proxy+}", "x")) for path, _method in ProtocolPaths.ROUTES)

    def test_the_terraform_module_creates_exactly_the_verbs_the_application_registers(self):
        """One method per verb (not ``ANY``): the module and ``ROUTES`` must not drift apart, or a route is 403 at the gateway."""
        main_tf = Path(__file__).resolve().parents[2] / "ak-deployment/ak-aws/serverless/modules/api-gateway/main.tf"
        if not main_tf.exists():
            pytest.skip("the Terraform module is not in this checkout")
        declared = re.search(r"proxy_methods\s*=\s*\[([^\]]*)\]", main_tf.read_text())
        assert declared, "proxy_methods not found in the api-gateway module"
        module_verbs = set(re.findall(r'"([A-Z]+)"', declared.group(1)))

        assert module_verbs == {method for _path, method in ProtocolPaths.ROUTES}
        assert "ANY" not in module_verbs

    def test_each_hosted_prefix_has_its_own_route_and_a_proxy_route(self):
        paths = {path for path, _method in ProtocolPaths.ROUTES}

        assert all(prefix in paths and f"{prefix}/{{proxy+}}" in paths for prefix in ProtocolPaths.PREFIXES)


# ---- the host -------------------------------------------------------------------------------------------------------

BASE = "/api/v1"
TOKEN = "alice-secret"  # what the ``static_identity`` fixture authenticates as ``alice``
PUBLIC_URLS = {
    "AK_A2A__URL": "https://abc.execute-api.us-east-1.amazonaws.com/agents/api/v1/a2a",
    "AK_MCP__URL": "https://abc.execute-api.us-east-1.amazonaws.com/agents/api/v1/mcp",
}
DEPLOYMENT = {
    "AK_CONFIG_PATH_OVERRIDE": "/nonexistent/config.yaml",
    "AK_EXECUTION__MODE": "rest_sync",
    "AK_EXECUTION__QUEUES__TYPE": "sqs",
    "AK_EXECUTION__RESPONSE_STORE__TYPE": "dynamodb",
    "AK_A2A__ENABLED": "true",
    "AK_MCP__ENABLED": "true",
    "AK_MCP__EXPOSE_AGENTS": "true",
    "AK_MCP__STATELESS_HTTP": "true",
    "API_BASE_PATH": "api",
    "API_VERSION": "v1",
    "AGENT_ENDPOINT": "agent",
    **PUBLIC_URLS,
}
ROUTER_MODULE = "agentkernel.deployment.aws.serverless.core.router.rest_lambda"


class _NoRunner(Runner):
    async def run(self, agent, session, requests):  # pragma: no cover - the queue client answers, never a runner
        raise AssertionError("not run")

    async def stream(self, agent, session, requests):  # pragma: no cover
        raise NotImplementedError()
        yield


class _Agent(Agent):
    """An agent the registry knows: the cards and the MCP tools are built from its descriptor."""

    def __init__(self, name: str):
        super().__init__(name, _NoRunner("NoRunner"))

    def _build_descriptor(self):
        return super()._build_descriptor().model_copy(update={"description": "Answers questions"})

    def get_description(self) -> str:
        return "You answer questions."

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


class FakeQueue:
    """Stands in for the ``RestHandler`` queue client of both surfaces: records each call, then answers or raises."""

    def __init__(self, reply: QueuedReply | None = None, delay: float = 0.0, raises: Exception | None = None):
        self.reply = reply
        self.delay = delay
        self.raises = raises
        self.calls: list = []

    async def request(self, body, protocol):
        self.calls.append((body, protocol))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raises is not None:
            raise self.raises
        return self.reply


def _queued(text: str = "pong") -> QueuedReply:
    """The reply a runner really stores: the body ``ResponseBuilder`` builds from an agent reply."""
    _status, body = ResponseBuilder.build_response(200, "s1", rest_api_mode=False, result=AgentReplyText(response=text))
    return QueuedReply(request_id="r1", status_code=200, body=body)


def _drop_the_host_loop() -> None:
    """Cancel what a test left parked (the held lifespan) and forget the class-level loop."""
    loop = LambdaProtocolHost._loop
    if loop is not None and not loop.is_closed():

        async def drain():
            pending = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

        loop.run_until_complete(drain())
        loop.close()
    LambdaProtocolHost._loop = None


@pytest.fixture
def deployment(monkeypatch, static_identity):
    """A deployment the host accepts, with A2A and MCP state fresh and the queue client of each surface restored after."""
    for name, value in DEPLOYMENT.items():
        monkeypatch.setenv(name, value)
    AKConfig._reset()
    saved_a2a = (A2A._cards, A2A._executors, A2A._built, A2A._client)
    saved_mcp = (MCP._fastmcp, MCP._built, MCP._executors, MCP._client)
    A2A._cards, A2A._executors, A2A._built = {}, {}, False
    MCP._fastmcp, MCP._built, MCP._executors = None, False, {}
    _drop_the_host_loop()
    yield
    _drop_the_host_loop()
    A2A._cards, A2A._executors, A2A._built, A2A._client = saved_a2a
    MCP._fastmcp, MCP._built, MCP._executors, MCP._client = saved_mcp
    AKConfig._reset()


class Deployed:
    """A built host and the fake queue behind both surfaces."""

    def __init__(self, host: LambdaProtocolHost, queue: FakeQueue):
        self.host = host
        self.queue = queue


@pytest.fixture
def deployed(deployment):
    """The host, built the way the application builds it: agents registered first, then ``LambdaProtocolHost()``."""
    queue = FakeQueue(_queued("pong"))
    A2A._client = queue
    MCP._client = queue
    with Runtime(InMemorySessionStore()) as runtime:
        runtime.register(_Agent("triage"))
        yield Deployed(LambdaProtocolHost(), queue)


def _api_event(method: str, path: str, resource: str | None = None, body: dict | None = None, headers: dict | None = None) -> dict:
    """An API Gateway proxy event for ``/api/v1<path>``, as the gateway sends it (the resource template, no stage in ``path``)."""
    return {
        "httpMethod": method,
        "path": f"{BASE}{path}",
        "resource": f"{BASE}{resource or path}",
        "pathParameters": None,
        "headers": {
            name: value
            for name, value in {"Host": "abc.execute-api.us-east-1.amazonaws.com", "Authorization": f"Bearer {TOKEN}", **(headers or {})}.items()
            if value is not None  # a header passed as None is left out: a call with no token has no Authorization header at all
        },
        "multiValueHeaders": None,
        "queryStringParameters": None,
        "multiValueQueryStringParameters": None,
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
        "requestContext": {"domainName": "abc.execute-api.us-east-1.amazonaws.com", "identity": {"sourceIp": "203.0.113.9"}},
    }


def _a2a_send(prompt: str = "hello", context_id: str = "ctx-1", configuration: dict | None = None, **event) -> dict:
    message = {"message": {"messageId": "m-1", "contextId": context_id, "role": "ROLE_USER", "parts": [{"text": prompt}]}}
    if configuration is not None:
        message["configuration"] = configuration
    return _api_event(
        "POST",
        "/a2a/triage/message:send",
        "/a2a/{proxy+}",
        message,
        {"Content-Type": "application/json", "A2A-Version": "1.0"},
        **event,
    )


def _mcp_tool_call(path: str = "/mcp/", prompt: str = "hi", session_id: str = "s1", call_id: int = 1) -> dict:
    body = {
        "jsonrpc": "2.0",
        "id": call_id,
        "method": "tools/call",
        "params": {"name": "triage", "arguments": {"session_id": session_id, "prompt": prompt}},
    }
    return _api_event("POST", path, "/mcp", body, MCP_HEADERS)


def _sse_events(proxy: dict) -> list[dict]:
    """Every JSON-RPC message in the event-stream body MCP answered with: progress notifications, then the result."""
    return [json.loads(line.removeprefix("data: ")) for line in proxy["body"].splitlines() if line.startswith("data: ")]


def _sse_json(proxy: dict) -> dict:
    """The JSON-RPC response to the call (the message that answers its id), out of the whole buffered stream."""
    [response] = [event for event in _sse_events(proxy) if "id" in event]
    return response


class TestServingA2A:
    def test_a_message_send_is_answered_with_the_agents_reply(self, deployed):
        proxy = deployed.host.handle(_a2a_send("hello"), None)

        assert proxy["statusCode"] == 200
        assert "pong" in proxy["body"]

    def test_the_call_reaches_the_queue_as_one_tagged_request_on_the_callers_session(self, deployed):
        deployed.host.handle(_a2a_send("hello", context_id="ctx-9"), None)

        [(body, protocol)] = deployed.queue.calls
        assert protocol == "a2a"
        assert (body.prompt, body.agent, body.session_id) == ("hello", "triage", "ctx-9")
        assert body.principal.subject == "alice"

    def test_the_public_agent_card_needs_no_token(self, deployed):
        proxy = deployed.host.handle(
            _api_event("GET", "/a2a/triage/.well-known/agent-card.json", "/a2a/{proxy+}", headers={"Authorization": None}), None
        )

        assert proxy["statusCode"] == 200
        card = json.loads(proxy["body"])
        assert card["name"] == "triage"
        assert card["supportedInterfaces"][0]["url"] == f"{PUBLIC_URLS['AK_A2A__URL']}/triage"

    def test_the_catalog_lists_the_agents_the_registry_knows(self, deployed):
        proxy = deployed.host.handle(_api_event("GET", "/a2a/catalog", "/a2a/{proxy+}"), None)

        assert proxy["statusCode"] == 200
        assert "triage" in proxy["body"]

    def test_return_immediately_still_waits_for_the_reply(self, deployed):
        """The executor sends one message, never a task, so the SDK has nothing to return early with (spec Deviation 2)."""
        deployed.queue.delay = 0.3
        plain = deployed.host.handle(_a2a_send("hello"), None)
        immediate = deployed.host.handle(_a2a_send("hello", configuration={"returnImmediately": True}), None)

        assert immediate["statusCode"] == plain["statusCode"] == 200
        assert "pong" in immediate["body"]
        assert [protocol for _body, protocol in deployed.queue.calls] == ["a2a", "a2a"]


class TestServingMCP:
    def test_a_tool_call_is_answered_as_one_whole_event_stream(self, deployed):
        proxy = deployed.host.handle(_mcp_tool_call(), None)

        assert proxy["statusCode"] == 200
        assert proxy["multiValueHeaders"]["content-type"] == ["text/event-stream"]
        assert _sse_json(proxy)["result"]["content"][0]["text"] == "pong"

    def test_the_whole_stream_is_buffered_not_just_the_last_event(self, deployed):
        """The executor sends progress notifications before the result: all of them are in the one body."""
        events = _sse_events(deployed.host.handle(_mcp_tool_call(), None))

        assert [event.get("method") for event in events] == ["notifications/message", "notifications/message", None]
        assert "result" in events[-1]

    def test_the_call_reaches_the_queue_as_one_tagged_request(self, deployed):
        deployed.host.handle(_mcp_tool_call(prompt="hi", session_id="s-7"), None)

        [(body, protocol)] = deployed.queue.calls
        assert protocol == "mcp"
        assert (body.prompt, body.agent, body.session_id) == ("hi", "triage", "s-7")
        assert body.principal.subject == "alice"

    @pytest.mark.parametrize("path", ["/mcp", "/mcp/"])
    def test_mcp_is_served_with_and_without_the_trailing_slash_and_never_redirects(self, deployed, path):
        """The app redirects ``/mcp`` to ``/mcp/`` with a ``Location`` that lacks the stage; the host calls ``/mcp/`` itself (Deviation 9)."""
        proxy = deployed.host.handle(_mcp_tool_call(path=path), None)

        assert proxy["statusCode"] == 200
        assert "location" not in {name.lower() for name in proxy["multiValueHeaders"]}

    def test_a_get_for_server_push_is_a_405(self, deployed):
        """Stateless MCP answers a GET with 405 on its own (spec Deviation 4); the host adds no code for it."""
        proxy = deployed.host.handle(_api_event("GET", "/mcp", headers={"Accept": "text/event-stream"}), None)

        assert proxy["statusCode"] == 405

    def test_a_call_with_no_token_is_refused_by_mcp_itself(self, deployed):
        """``/mcp`` bypasses the API Gateway authorizer, so FastMCP's own check is the one that refuses it."""
        proxy = deployed.host.handle(
            _api_event("POST", "/mcp", body={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers={"Authorization": None, **MCP_HEADERS}), None
        )

        assert proxy["statusCode"] == 401
        assert deployed.queue.calls == []


class TestTheLifespan:
    def test_it_is_started_once_and_stays_open_across_calls(self, deployment, monkeypatch):
        starts = []
        original = AppLifespan.start

        async def counting_start(self):
            starts.append(1)
            await original(self)

        monkeypatch.setattr(AppLifespan, "start", counting_start)
        A2A._client = MCP._client = FakeQueue(_queued("pong"))
        with Runtime(InMemorySessionStore()) as runtime:
            runtime.register(_Agent("triage"))
            host = LambdaProtocolHost()
            answers = [host.handle(_mcp_tool_call(call_id=call_id), None) for call_id in (1, 2, 3)]

        assert starts == [1]
        assert [answer["statusCode"] for answer in answers] == [200, 200, 200]

    def test_a_lifespan_that_fails_to_start_fails_the_construction(self, deployment, monkeypatch):
        @asynccontextmanager
        async def lifespan(app):
            raise RuntimeError("startup failed")
            yield

        monkeypatch.setattr(RESTAPI, "build_app", classmethod(lambda cls, handlers=None: FastAPI(lifespan=lifespan)))

        with pytest.raises(RuntimeError, match="startup failed"):
            LambdaProtocolHost()


class TestBuildingTheHost:
    def test_the_direct_chat_routes_are_not_built(self, deployment, monkeypatch):
        """``handlers=[]``, not ``None``: ``None`` would build the direct chat routes, which run agents in this process."""
        handlers_seen = []
        build = RESTAPI.build_app.__func__

        def spy(cls, handlers=None):
            handlers_seen.append(handlers)
            return build(cls, handlers=handlers)

        monkeypatch.setattr(RESTAPI, "build_app", classmethod(spy))
        A2A._client = MCP._client = FakeQueue(_queued())
        with Runtime(InMemorySessionStore()) as runtime:
            runtime.register(_Agent("triage"))
            LambdaProtocolHost()

        assert handlers_seen == [[]]

    def test_a_deployment_the_guard_refuses_fails_before_the_app_is_built(self, deployment, monkeypatch):
        monkeypatch.setenv("AK_EXECUTION__MODE", "async")
        AKConfig._reset()
        monkeypatch.setattr(RESTAPI, "build_app", classmethod(lambda cls, handlers=None: pytest.fail("the app was built")))

        with pytest.raises(AKConfigError, match="got async"):
            LambdaProtocolHost()


class TestThePathTheAppSees:
    @pytest.fixture
    def host(self, deployed):
        return deployed.host

    @pytest.mark.parametrize(
        "event_path, app_path",
        [
            ("/api/v1/a2a/triage/message:send", "/a2a/triage/message:send"),
            ("/api/v1/a2a/catalog", "/a2a/catalog"),
            ("/api/v1/a2a", "/a2a"),
            ("/api/v1/mcp", "/mcp/"),
            ("/api/v1/mcp/", "/mcp/"),
            ("/api/v1/mcp/anything", "/mcp/anything"),
            ("/a2a/triage/message:send", "/a2a/triage/message:send"),
        ],
    )
    def test_the_base_path_is_removed_and_the_exact_mcp_path_gains_its_slash(self, host, event_path, app_path):
        assert host._app_path({"path": event_path}) == app_path

    @pytest.mark.parametrize("event_path", ["/api/v1/health", "/api/v1/chat", "/api/v1", "/api/v10/a2a/x", "/other/a2a/x", "/"])
    def test_anything_that_is_not_a2a_or_mcp_is_a_404(self, host, event_path):
        with pytest.raises(HTTPException) as refused:
            host._app_path({"path": event_path})

        assert refused.value.status_code == 404

    def test_the_app_is_never_asked_for_a_path_it_does_not_serve(self, host):
        proxy = host.handle(_api_event("GET", "/health"), None)

        assert proxy["statusCode"] == 404
        assert json.loads(proxy["body"]) == {"detail": "Not Found"}


class TestFailuresAreProxyResponses:
    def test_an_unexpected_error_is_a_generic_500_that_never_carries_its_text(self, deployed, caplog):
        async def failing(app, event, app_path):
            raise RuntimeError("secret internal detail")

        with patch.object(deployed.host._translator, "call_app", failing), caplog.at_level(logging.ERROR):
            proxy = deployed.host.handle(_a2a_send(), None)

        assert proxy["statusCode"] == 500
        assert proxy["body"] == "Internal Server Error"
        assert "secret internal detail" not in proxy["body"]
        assert "secret internal detail" in caplog.text

    def test_a_body_that_is_not_valid_base64_is_a_500_not_an_exception(self, deployed):
        event = _a2a_send()
        event["isBase64Encoded"] = True
        event["body"] = "not base64 !!"

        proxy = deployed.host.handle(event, None)

        assert proxy["statusCode"] == 500

    def test_a_timeout_waiting_for_the_agent_reaches_the_caller_as_an_a2a_error(self, deployed, caplog):
        deployed.queue.raises = ReplyTimeoutError("r9", 5, 5.0)

        proxy = deployed.host.handle(_a2a_send(), None)

        assert proxy["statusCode"] == 500
        assert A2A.Executor.TIMEOUT_MESSAGE in proxy["body"]

    def test_a_runner_failure_reaches_the_caller_as_an_mcp_tool_error_with_a_fixed_message(self, deployed):
        deployed.queue.reply = QueuedReply(request_id="r1", status_code=500, body={"error": "internal db password leaked", "session_id": "s1"})

        proxy = deployed.host.handle(_mcp_tool_call(), None)

        result = _sse_json(proxy)["result"]
        assert result["isError"] is True
        assert MCP.Executor.ERROR_MESSAGE in result["content"][0]["text"]
        assert "password" not in proxy["body"]


class TestTheWaitBudgetWarning:
    @staticmethod
    def _context(remaining_millis: int) -> MagicMock:
        context = MagicMock()
        context.get_remaining_time_in_millis.return_value = remaining_millis
        return context

    def _warnings(self, caplog) -> list[str]:
        return [record.getMessage() for record in caplog.records if record.name == "ak.aws.lambda.protocol" and record.levelno == logging.WARNING]

    def test_a_wait_longer_than_the_time_left_is_warned_about_once_per_call(self, deployed, caplog):
        """Defaults wait 20 s; the Lambda has 5 s left."""
        with caplog.at_level(logging.WARNING, logger="ak.aws.lambda.protocol"):
            deployed.host.handle(_a2a_send(), self._context(5_000))

        [warning] = self._warnings(caplog)
        assert "20s" in warning and "5s left" in warning
        assert "execution.response_store.retry_count x delay" in warning

    def test_enough_time_left_is_silent(self, deployed, caplog):
        with caplog.at_level(logging.WARNING, logger="ak.aws.lambda.protocol"):
            deployed.host.handle(_a2a_send(), self._context(60_000))

        assert self._warnings(caplog) == []

    def test_a_context_without_a_clock_is_silent(self, deployed, caplog):
        with caplog.at_level(logging.WARNING, logger="ak.aws.lambda.protocol"):
            deployed.host.handle(_a2a_send(), None)

        assert self._warnings(caplog) == []

    def test_the_call_is_served_even_when_the_wait_is_too_long(self, deployed):
        proxy = deployed.host.handle(_a2a_send(), self._context(5_000))

        assert proxy["statusCode"] == 200


class TestRegisteredWithTheRouter:
    """The application registers ``handle`` for every route in ``ProtocolPaths.ROUTES``; ``Lambda.handler`` dispatches to it."""

    @pytest.fixture
    def lambda_handler(self, deployed):
        Lambda._router = None
        Lambda._config = None
        endpoints = MagicMock()
        endpoints.get_default_endpoint_info.return_value = ("default_chat_path", "POST", "GET")
        endpoints.get_routes.return_value = {"default_chat_path": {"POST": MagicMock(return_value=(200, {"via": "chat"}))}}
        with patch(f"{ROUTER_MODULE}.DefaultEndpointsHandler", return_value=endpoints):
            for path, method in ProtocolPaths.ROUTES:
                Lambda.register(path, method=method)(deployed.host.handle)
            yield Lambda.handler
        Lambda._router = None
        Lambda._config = None

    def test_an_a2a_message_send_reaches_the_agent(self, lambda_handler, deployed):
        response = lambda_handler(_a2a_send("hello"), None)

        assert response["statusCode"] == 200
        assert "pong" in response["body"]
        assert [protocol for _body, protocol in deployed.queue.calls] == ["a2a"]

    def test_an_mcp_tool_call_reaches_the_agent(self, lambda_handler, deployed):
        response = lambda_handler(_mcp_tool_call(path="/mcp"), None)

        assert response["statusCode"] == 200
        assert _sse_json(response)["result"]["content"][0]["text"] == "pong"
        assert [protocol for _body, protocol in deployed.queue.calls] == ["mcp"]

    def test_the_public_agent_card_is_served_through_the_proxy_route(self, lambda_handler):
        response = lambda_handler(_api_event("GET", "/a2a/triage/.well-known/agent-card.json", "/a2a/{proxy+}"), None)

        assert response["statusCode"] == 200
        assert json.loads(response["body"])["name"] == "triage"

    def test_the_chat_route_still_dispatches_as_before(self, lambda_handler):
        response = lambda_handler({"httpMethod": "POST", "path": "/api/v1/agent", "resource": "/api/v1/agent"}, None)

        assert json.loads(response["body"]) == {"via": "chat"}
