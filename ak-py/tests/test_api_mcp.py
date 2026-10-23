from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastmcp.exceptions import ToolError

from agentkernel.api.mcp.akmcp import MCP
from agentkernel.core.chat_service import ResponseBuilder
from agentkernel.pipeline.request_client import QueuedReply, ReplyTimeoutError

MCP_NAME = "Agent Kernel FastMCP Instance"


@pytest.fixture(autouse=True)
def reset_mcp_state():
    """MCP keeps its FastMCP instance in class state; restore it so tests don't leak into each other."""
    saved = (MCP._fastmcp, MCP._built, dict(MCP._executors), MCP._client)
    MCP._fastmcp = None
    MCP._built = False
    MCP._executors = {}
    try:
        yield
    finally:
        MCP._fastmcp, MCP._built, MCP._executors, MCP._client = saved


class FakeClient:
    """Stands in for QueueRequestClient: records each request and answers with ``reply`` or raises ``raises``."""

    def __init__(self, reply=None, raises=None):
        self.reply = reply
        self.raises = raises
        self.calls = []

    async def request(self, body, protocol):
        self.calls.append((body, protocol))
        if self.raises is not None:
            raise self.raises
        return self.reply


def _queue_reply(agent_reply, status_code=200) -> FakeClient:
    """Install a client answering with the body a runner really stores for ``agent_reply``."""
    _status, body = ResponseBuilder.build_response(status_code, "s1", rest_api_mode=False, result=agent_reply)
    MCP._client = FakeClient(QueuedReply(request_id="r1", status_code=status_code, body=body))
    return MCP._client


def _config(stateless_http: bool) -> Mock:
    """Mock AKConfig with MCP enabled and agent exposure off (so Runtime isn't touched)."""
    config = Mock()
    config.mcp.enabled = True
    config.mcp.expose_agents = False
    config.mcp.stateless_http = stateless_http
    return config


class TestMCPHttpApp:
    """`MCP.get_http_app()` must keep applying `mcp.stateless_http` to the served app."""

    @pytest.mark.parametrize("stateless_http", [True, False])
    def test_get_http_app_passes_configured_stateless_http(self, stateless_http):
        """fastmcp 3 removed the `FastMCP(stateless_http=...)` kwarg; the config value now rides on `http_app()`."""
        fastmcp = Mock()
        MCP._fastmcp = fastmcp
        MCP._built = True

        with patch("agentkernel.api.mcp.akmcp.AKConfig") as mock_config_class:
            mock_config_class.get.return_value = _config(stateless_http)
            app = MCP.get_http_app()

        fastmcp.http_app.assert_called_once_with(path="/", stateless_http=stateless_http)
        assert app is fastmcp.http_app.return_value

    def test_build_does_not_pass_stateless_http_to_constructor(self):
        """Passing `stateless_http` to the constructor raises TypeError on fastmcp >= 3.0."""
        with patch("agentkernel.api.mcp.akmcp.FastMCP") as mock_fastmcp_class, patch("agentkernel.api.mcp.akmcp.AKConfig") as mock_config_class:
            mock_config_class.get.return_value = _config(True)
            MCP.get_http_app()

        mock_fastmcp_class.assert_called_once_with(MCP_NAME)
        instance = mock_fastmcp_class.return_value
        instance.http_app.assert_called_once_with(path="/", stateless_http=True)

    def test_get_http_app_skips_rebuild_for_existing_instance(self):
        """A second call must not rebuild the server, but must still apply the configured mode."""
        fastmcp = Mock()

        with (
            patch("agentkernel.api.mcp.akmcp.FastMCP", return_value=fastmcp) as mock_fastmcp_class,
            patch("agentkernel.api.mcp.akmcp.AKConfig") as mock_config_class,
        ):
            mock_config_class.get.return_value = _config(True)
            MCP.get_http_app()
            MCP.get_http_app()

        mock_fastmcp_class.assert_called_once_with(MCP_NAME)
        assert fastmcp.http_app.call_count == 2
        assert fastmcp.http_app.call_args_list[-1].kwargs == {"path": "/", "stateless_http": True}


class TestExecutorReplyShapes:
    """The executor's three outcomes: a labelled payload, an unlabelled one, and text.

    Verified against the pinned fastmcp: a ToolResult carrying `meta` round-trips to a client, so
    the format label travels in MCP's own `_meta` slot rather than an Agent Kernel envelope. Each
    reply is the body a runner stores (`ResponseBuilder`), so these run over the bytes the queue carries.
    """

    @pytest.mark.asyncio
    async def test_labelled_reply_returns_a_tool_result_with_meta(self):
        from unittest.mock import AsyncMock, patch

        from fastmcp.tools.tool import ToolResult

        from agentkernel.api.mcp.akmcp import MCP
        from agentkernel.core.model import AgentReplyAny

        content = {"version": "v1.0", "createSurface": {"surfaceId": "s1"}}
        reply = AgentReplyAny(content=content, media_type="application/a2ui+json")

        _queue_reply(reply)
        result = await MCP.Executor("a").execute("s1", "hi", AsyncMock())

        assert isinstance(result, ToolResult)
        assert result.structured_content == content
        assert result.meta == {"media_type": "application/a2ui+json"}

    @pytest.mark.asyncio
    async def test_unlabelled_structured_reply_still_returns_its_string(self):
        from unittest.mock import AsyncMock, patch

        from agentkernel.api.mcp.akmcp import MCP
        from agentkernel.core.model import AgentReplyAny

        _queue_reply(AgentReplyAny(content={"a": 1}))
        result = await MCP.Executor("a").execute("s1", "hi", AsyncMock())

        assert result == '{"a": 1}'

    @pytest.mark.asyncio
    async def test_text_reply_returns_its_text(self):
        from unittest.mock import AsyncMock, patch

        from agentkernel.api.mcp.akmcp import MCP
        from agentkernel.core.model import AgentReplyText

        _queue_reply(AgentReplyText(response="hello"))
        result = await MCP.Executor("a").execute("s1", "hi", AsyncMock())

        assert result == "hello"

    @pytest.mark.asyncio
    async def test_a_list_payload_travels_under_result(self):
        """MCP's `structuredContent` is an object, so an array payload cannot be sent bare.

        fastmcp enforces it: `ToolResult(structured_content=[...])` raises `ValueError`. A2UI on
        v0.9.1 is a message sequence, so this is a first-class payload shape, not an edge case.
        """
        from unittest.mock import AsyncMock, patch

        from fastmcp.tools.tool import ToolResult

        from agentkernel.api.mcp.akmcp import MCP
        from agentkernel.core.model import AgentReplyAny

        content = [{"createSurface": {"surfaceId": "s1"}}, {"updateComponents": {}}]
        reply = AgentReplyAny(content=content, media_type="application/a2ui+json")

        _queue_reply(reply)
        result = await MCP.Executor("a").execute("s1", "hi", AsyncMock())

        assert isinstance(result, ToolResult)
        assert result.structured_content == {"result": content}
        assert result.meta == {"media_type": "application/a2ui+json", "fastmcp": {"wrap_result": True}}

    @pytest.mark.asyncio
    async def test_a_wrapped_list_reaches_a_client_unwrapped(self):
        """The wrap is transparent: `fastmcp.wrap_result` is what the client reads to undo it.

        Asserted through a real client rather than on the ToolResult, because the claim is about
        what the caller receives — without the flag they would have to know about `result`.
        """
        from unittest.mock import AsyncMock, patch

        from fastmcp import Client, FastMCP

        from agentkernel.api.mcp.akmcp import MCP
        from agentkernel.core.model import AgentReplyAny

        content = [{"createSurface": {"surfaceId": "s1"}}]
        reply = AgentReplyAny(content=content, media_type="application/a2ui+json")

        server = FastMCP(MCP_NAME)
        server.tool(MCP.Executor("a").execute, name="a", description="test agent")

        _queue_reply(reply)
        async with Client(server) as client:
            result = await client.call_tool("a", {"session_id": "s1", "prompt": "hi"})

        assert result.structured_content == {"result": content}
        assert result.data == content
        assert result.meta["media_type"] == "application/a2ui+json"

    @pytest.mark.asyncio
    async def test_an_image_reply_returns_the_runners_text(self):
        """The runner's body is now the only source of reply text, and it names the image (#780)."""
        from unittest.mock import AsyncMock

        from agentkernel.api.mcp.akmcp import MCP
        from agentkernel.core.model import AgentReplyImage

        _queue_reply(AgentReplyImage(response="here it is", name="chart.png", image_data="aGk="))
        result = await MCP.Executor("a").execute("s1", "hi", AsyncMock())

        assert result == "here it is. Image chart.png is attached."


class TestExecutorThroughTheQueue:
    """What the executor sends, and how each failure reaches the caller (#780 §4)."""

    @pytest.mark.asyncio
    async def test_the_request_is_the_tool_arguments_and_the_agent(self):
        from agentkernel.core.model import AgentReplyText

        client = _queue_reply(AgentReplyText(response="hi"))

        await MCP.Executor("triage").execute("s9", "what is 2+2", AsyncMock())

        [(body, protocol)] = client.calls
        assert (body.prompt, body.agent, body.session_id) == ("what is 2+2", "triage", "s9")
        assert protocol == "mcp" == MCP.PROTOCOL

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "client, message",
        [
            (FakeClient(QueuedReply(request_id="r1", status_code=500, body={"error": "database password is hunter2"})), MCP.Executor.ERROR_MESSAGE),
            (FakeClient(QueuedReply(request_id="r1", body={"session_id": "s1"})), MCP.Executor.ERROR_MESSAGE),
            (FakeClient(raises=ReplyTimeoutError("r1", 60, 1.0)), MCP.Executor.TIMEOUT_MESSAGE),
            (FakeClient(raises=ConnectionError("broker at 10.0.0.5 refused")), MCP.Executor.ERROR_MESSAGE),
        ],
        ids=["error-status", "missing-result", "timeout", "exception"],
    )
    async def test_every_failure_is_a_tool_error_with_a_fixed_message(self, client, message):
        MCP._client = client

        with pytest.raises(ToolError) as excinfo:
            await MCP.Executor("a").execute("s1", "hi", AsyncMock())

        assert str(excinfo.value) == message

    @pytest.mark.asyncio
    async def test_a_client_sees_only_the_fixed_message(self):
        from fastmcp import Client, FastMCP

        MCP._client = FakeClient(raises=ConnectionError("broker at 10.0.0.5 refused"))
        server = FastMCP(MCP_NAME)
        server.tool(MCP.Executor("a").execute, name="a", description="test agent")

        async with Client(server) as client:
            result = await client.call_tool("a", {"session_id": "s1", "prompt": "hi"}, raise_on_error=False)

        assert result.is_error
        assert result.content[0].text == MCP.Executor.ERROR_MESSAGE

    def test_the_module_no_longer_runs_agents_itself(self):
        import agentkernel.api.mcp.akmcp as module

        assert not hasattr(module, "AgentService")

    def test_the_client_is_built_once_and_reused(self, monkeypatch):
        from agentkernel.pipeline import request_client

        built = []

        class _Client:
            def __init__(self):
                built.append(self)

        monkeypatch.setattr(request_client, "QueueRequestClient", _Client)
        MCP._client = None

        assert MCP.get_client() is MCP.get_client()
        assert len(built) == 1
