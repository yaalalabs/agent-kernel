"""LambdaEventTranslator: API Gateway REST (v1) proxy events <-> Starlette (#760, part 2)."""

import asyncio
import base64
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException
from starlette.responses import Response, StreamingResponse

from agentkernel.core.config import AKConfig
from agentkernel.deployment.aws.serverless.core.event_translator import LambdaEventTranslator


def _event(**overrides) -> dict:
    event = {
        "httpMethod": "POST",
        "path": "/api/v1/slack/events",
        "headers": {"Host": "abc.execute-api.us-east-1.amazonaws.com", "Content-Type": "application/json"},
        "multiValueHeaders": None,
        "queryStringParameters": None,
        "multiValueQueryStringParameters": None,
        "body": '{"hello": "world"}',
        "isBase64Encoded": False,
        "requestContext": {"domainName": "abc.execute-api.us-east-1.amazonaws.com", "identity": {"sourceIp": "203.0.113.9"}},
    }
    event.update(overrides)
    return event


def _run(coro):
    return asyncio.run(coro)


async def _body(request):
    return await request.body()


translator = LambdaEventTranslator()


class TestBodies:
    def test_a_plain_body_is_byte_exact(self):
        payload = '{"text": "héllo ✓"}'
        request = translator.to_request(_event(body=payload))

        assert _run(_body(request)) == payload.encode("utf-8")

    def test_a_base64_body_is_decoded_byte_exact(self):
        binary = bytes(range(256))
        request = translator.to_request(_event(body=base64.b64encode(binary).decode(), isBase64Encoded=True))

        assert _run(_body(request)) == binary

    def test_a_missing_body_is_empty(self):
        assert _run(_body(translator.to_request(_event(body=None)))) == b""

    def test_the_body_can_be_read_twice(self):
        async def _twice(request):
            return await request.body(), await request.json()

        assert _run(_twice(translator.to_request(_event()))) == (b'{"hello": "world"}', {"hello": "world"})


class TestHeadersAndQuery:
    def test_a_repeated_header_keeps_both_values(self):
        request = translator.to_request(_event(multiValueHeaders={"X-Forwarded-For": ["1.1.1.1", "2.2.2.2"], "Host": ["h.example"]}))

        assert request.headers.getlist("x-forwarded-for") == ["1.1.1.1", "2.2.2.2"]

    def test_header_lookup_is_case_insensitive(self):
        request = translator.to_request(_event(headers={"X-Hub-Signature-256": "sha256=abc"}))

        assert request.headers["x-hub-signature-256"] == "sha256=abc"
        assert request.headers["X-Hub-Signature-256"] == "sha256=abc"

    def test_multi_value_headers_win_over_single_value_headers(self):
        request = translator.to_request(_event(headers={"X-A": "single"}, multiValueHeaders={"X-A": ["multi"]}))

        assert request.headers.getlist("x-a") == ["multi"]

    def test_a_repeated_query_key_keeps_both_values(self):
        request = translator.to_request(_event(multiValueQueryStringParameters={"tag": ["a", "b"], "q": ["x y"]}))

        assert request.query_params.getlist("tag") == ["a", "b"]
        assert request.query_params["q"] == "x y"

    def test_single_value_maps_alone_still_yield_headers_and_query(self):
        request = translator.to_request(_event(headers={"X-Only": "1"}, queryStringParameters={"hub.mode": "subscribe"}))

        assert request.headers["x-only"] == "1"
        assert request.query_params["hub.mode"] == "subscribe"

    def test_a_meta_handshake_in_the_single_value_shape_returns_the_challenge(self, monkeypatch):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        monkeypatch.setenv("AK_WHATSAPP__ACCESS_TOKEN", "token")
        monkeypatch.setenv("AK_WHATSAPP__PHONE_NUMBER_ID", "phone-1")
        monkeypatch.setenv("AK_WHATSAPP__VERIFY_TOKEN", "verify-me")
        AKConfig._reset()
        from agentkernel.integration.whatsapp.adapter import WhatsAppInboundAdapter

        event = _event(
            httpMethod="GET",
            path="/api/v1/whatsapp/webhook",
            body=None,
            queryStringParameters={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "12345"},
        )
        try:
            assert _run(WhatsAppInboundAdapter().challenge(translator.to_request(event))) == 12345
        finally:
            AKConfig._reset()


class TestScope:
    def test_method_path_scheme_and_server_come_from_the_event(self):
        request = translator.to_request(_event(httpMethod="post"))

        assert request.method == "POST"
        assert request.url.path == "/api/v1/slack/events"
        assert request.url.scheme == "https"
        assert request.scope["server"] == ("abc.execute-api.us-east-1.amazonaws.com", 443)
        assert request.client.host == "203.0.113.9"

    def test_forwarded_headers_set_the_scheme_and_port(self):
        request = translator.to_request(_event(headers={"Host": "h.example", "X-Forwarded-Proto": "http", "X-Forwarded-Port": "8080"}))

        assert request.url.scheme == "http"
        assert request.scope["server"] == ("h.example", 8080)

    @pytest.mark.parametrize("port, proto", [("443, 8443", "https, http"), ("not-a-port", "https")])
    def test_comma_joined_or_malformed_forwarded_headers_do_not_fail_the_request(self, port, proto):
        request = translator.to_request(_event(headers={"Host": "h.example", "X-Forwarded-Port": port, "X-Forwarded-Proto": proto}))

        assert request.url.scheme == "https"
        assert request.scope["server"] == ("h.example", 443)

    def test_without_a_host_header_the_domain_name_is_the_server(self):
        request = translator.to_request(_event(headers={}))

        assert request.scope["server"] == ("abc.execute-api.us-east-1.amazonaws.com", 443)


def _fastapi_answer(value):
    app = FastAPI()

    @app.get("/")
    def _route():
        return value

    return TestClient(app).get("/")


class TestResponses:
    def test_a_starlette_response_passes_through(self):
        response = Response(content=b"raw-bytes", status_code=201, media_type="text/plain")
        response.set_cookie("a", "1")
        response.set_cookie("b", "2")

        proxy = _run(translator.to_proxy_response(None, response))

        assert proxy["statusCode"] == 201
        assert proxy["body"] == "raw-bytes"
        assert proxy["isBase64Encoded"] is False
        assert len(proxy["multiValueHeaders"]["set-cookie"]) == 2

    @pytest.mark.parametrize("value", [{"status": "ok"}, {"ok": True}, 12345])
    def test_plain_values_match_fastapi(self, value):
        proxy = _run(translator.to_proxy_response(None, value))
        expected = _fastapi_answer(value)

        assert proxy["statusCode"] == expected.status_code == 200
        assert proxy["body"].encode() == expected.content
        assert proxy["multiValueHeaders"]["content-type"] == ["application/json"]

    def test_a_non_utf8_body_is_base64(self):
        proxy = _run(translator.to_proxy_response(None, Response(content=b"\xff\xfe\x00", media_type="application/octet-stream")))

        assert proxy["isBase64Encoded"] is True
        assert base64.b64decode(proxy["body"]) == b"\xff\xfe\x00"

    def test_a_streaming_response_is_refused(self):
        with pytest.raises(TypeError, match="streaming"):
            _run(translator.to_proxy_response(None, StreamingResponse(iter([b"x"]))))


class TestErrors:
    def test_an_http_exception_keeps_its_status_headers_and_detail(self):
        proxy = _run(translator.error_to_proxy_response(HTTPException(403, detail="x", headers={"X-A": "1"})))

        assert proxy["statusCode"] == 403
        assert proxy["multiValueHeaders"]["x-a"] == ["1"]
        assert proxy["body"] == '{"detail":"x"}'

    def test_a_bodiless_status_has_no_body(self):
        proxy = _run(translator.error_to_proxy_response(HTTPException(304)))

        assert proxy["statusCode"] == 304
        assert proxy["body"] == ""

    def test_an_unexpected_error_is_a_generic_500(self, caplog):
        with caplog.at_level(logging.ERROR, logger="ak.aws.lambda.webhook"):
            proxy = _run(translator.error_to_proxy_response(RuntimeError("secret")))

        assert proxy["statusCode"] == 500
        assert proxy["body"] == "Internal Server Error"
        assert "secret" not in proxy["body"]
        assert "secret" in caplog.text


class ScriptedApp:
    """An ASGI app that sends the given messages and records the scope and body it was called with."""

    def __init__(self, messages):
        self.messages = messages
        self.scope = None
        self.body = None

    async def __call__(self, scope, receive, send):
        self.scope = scope
        self.body = (await receive())["body"]
        for message in self.messages:
            await send(message)


def _answer(status=200, headers=(), *chunks):
    """The ASGI messages for a response: a start, then one body message per chunk (the last one final)."""
    parts = list(chunks) or [b""]
    messages = [{"type": "http.response.start", "status": status, "headers": list(headers)}]
    messages += [{"type": "http.response.body", "body": chunk, "more_body": index < len(parts) - 1} for index, chunk in enumerate(parts)]
    return messages


class TestCallApp:
    """``call_app`` (#932): a whole ASGI app driven from an API Gateway event, answered as one proxy response."""

    def test_every_body_chunk_is_buffered_into_one_body(self):
        app = ScriptedApp(_answer(200, [(b"content-type", b"text/plain")], b"one,", b"two,", b"three"))

        proxy = _run(translator.call_app(app, _event(), "/x"))

        assert proxy["statusCode"] == 200
        assert proxy["body"] == "one,two,three"
        assert proxy["isBase64Encoded"] is False

    def test_an_sse_answer_is_buffered_whole(self):
        """MCP answers a tool call as text/event-stream; a proxy response is one body."""
        event_stream = [b"event: message\n", b'data: {"jsonrpc":"2.0","id":1,"result":{}}\n\n']
        app = ScriptedApp(_answer(200, [(b"content-type", b"text/event-stream")], *event_stream))

        proxy = _run(translator.call_app(app, _event(), "/mcp/"))

        assert proxy["statusCode"] == 200
        assert proxy["multiValueHeaders"]["content-type"] == ["text/event-stream"]
        assert proxy["body"] == 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{}}\n\n'

    def test_the_status_and_repeated_headers_are_kept(self):
        app = ScriptedApp(_answer(201, [(b"set-cookie", b"a=1"), (b"set-cookie", b"b=2"), (b"x-id", b"7")], b"ok"))

        proxy = _run(translator.call_app(app, _event(), "/x"))

        assert proxy["statusCode"] == 201
        assert proxy["multiValueHeaders"]["set-cookie"] == ["a=1", "b=2"]
        assert proxy["multiValueHeaders"]["x-id"] == ["7"]

    def test_a_non_utf8_answer_is_base64(self):
        app = ScriptedApp(_answer(200, [], b"\xff\xfe", b"\x00"))

        proxy = _run(translator.call_app(app, _event(), "/x"))

        assert proxy["isBase64Encoded"] is True
        assert base64.b64decode(proxy["body"]) == b"\xff\xfe\x00"

    def test_the_app_routes_on_app_path_not_the_event_path(self):
        app = ScriptedApp(_answer())

        _run(translator.call_app(app, _event(path="/api/v1/mcp"), "/mcp/"))

        assert app.scope["path"] == "/mcp/"
        assert app.scope["raw_path"] == b"/mcp/"
        assert app.scope["root_path"] == ""

    def test_the_app_scope_and_a_request_agree_on_everything_but_the_path(self):
        event = _event(
            httpMethod="GET",
            multiValueHeaders={"Host": ["h.example"], "X-Forwarded-Proto": ["http"], "X-Forwarded-Port": ["8080"], "Accept": ["a", "b"]},
            multiValueQueryStringParameters={"k": ["1", "2"]},
        )
        app = ScriptedApp(_answer())

        _run(translator.call_app(app, event, "/elsewhere"))
        request_scope = translator.to_request(event).scope

        assert {key: value for key, value in app.scope.items() if key not in ("path", "raw_path")} == {
            key: value for key, value in request_scope.items() if key not in ("path", "raw_path")
        }

    @pytest.mark.parametrize(
        "event_overrides, expected",
        [
            ({"body": '{"hello": "world"}'}, b'{"hello": "world"}'),
            ({"body": base64.b64encode(bytes(range(256))).decode(), "isBase64Encoded": True}, bytes(range(256))),
            ({"body": None}, b""),
        ],
    )
    def test_the_app_reads_the_exact_body_bytes(self, event_overrides, expected):
        app = ScriptedApp(_answer())

        _run(translator.call_app(app, _event(**event_overrides), "/x"))

        assert app.body == expected

    def test_a_listener_for_disconnects_hears_it_only_after_the_response_is_complete(self):
        """Starlette listens for a disconnect while it streams. Told at once, it would cut the answer short."""
        seen: dict = {}

        async def app(scope, receive, send):
            await receive()  # the body
            listener = asyncio.create_task(receive())
            await asyncio.sleep(0)
            seen["early"] = listener.done()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"x", "more_body": True})
            await asyncio.sleep(0)
            seen["mid_stream"] = listener.done()
            await send({"type": "http.response.body", "body": b"y", "more_body": False})
            await asyncio.sleep(0)
            seen["after"] = (listener.done(), listener.result())

        proxy = _run(translator.call_app(app, _event(), "/x"))

        assert seen == {"early": False, "mid_stream": False, "after": (True, {"type": "http.disconnect"})}
        assert proxy["body"] == "xy"

    def test_an_exception_from_the_app_reaches_the_host(self):
        async def app(scope, receive, send):
            raise RuntimeError("the app failed")

        with pytest.raises(RuntimeError, match="the app failed"):
            _run(translator.call_app(app, _event(), "/x"))

    def test_an_app_that_never_answers_is_an_error(self):
        async def app(scope, receive, send):
            await receive()

        with pytest.raises(RuntimeError, match="without starting a response"):
            _run(translator.call_app(app, _event(), "/x"))

    def test_a_real_fastapi_app_routes_validates_and_answers_as_it_would_on_uvicorn(self):
        app = FastAPI()

        @app.get("/hello/{name}")
        async def hello(name: str, shout: bool = False):
            return {"hello": name.upper() if shout else name}

        @app.post("/echo")
        async def echo(payload: dict):
            return payload

        @app.get("/gone")
        async def gone():
            raise HTTPException(410, detail="gone")

        found = _run(translator.call_app(app, _event(httpMethod="GET", body=None, queryStringParameters={"shout": "true"}), "/hello/ada"))
        posted = _run(translator.call_app(app, _event(body='{"a": 1}', headers={"Content-Type": "application/json"}), "/echo"))
        gone = _run(translator.call_app(app, _event(httpMethod="GET", body=None), "/gone"))
        missing = _run(translator.call_app(app, _event(httpMethod="GET", body=None), "/nope"))

        assert (found["statusCode"], found["body"]) == (200, '{"hello":"ADA"}')
        assert (posted["statusCode"], posted["body"]) == (200, '{"a":1}')
        assert (gone["statusCode"], gone["body"]) == (410, '{"detail":"gone"}')
        assert missing["statusCode"] == 404


class TestProxyResponseFromParts:
    def test_it_builds_the_proxy_response_from_a_status_raw_headers_and_a_body(self):
        proxy = LambdaEventTranslator.proxy_response_from_parts(202, [(b"Set-Cookie", b"a=1"), (b"Set-Cookie", b"b=2")], b"queued")

        assert proxy == {"statusCode": 202, "multiValueHeaders": {"Set-Cookie": ["a=1", "b=2"]}, "body": "queued", "isBase64Encoded": False}

    @pytest.mark.parametrize(
        "response",
        [
            Response(content=b"plain", status_code=201, media_type="text/plain"),
            Response(content=b"\xff\xfe\x00", media_type="application/octet-stream"),
            Response(status_code=204),
        ],
        ids=["text", "non-utf8", "no-content"],
    )
    def test_a_starlette_response_is_answered_exactly_as_before(self, response):
        """``_proxy_response`` now delegates here: the existing wire format must not move."""
        through_the_response = _run(translator.to_proxy_response(None, response))

        assert through_the_response == LambdaEventTranslator.proxy_response_from_parts(
            response.status_code, response.raw_headers, bytes(response.body)
        )
