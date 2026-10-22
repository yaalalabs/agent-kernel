from unittest.mock import Mock, patch

import pytest

from agentkernel.api.mcp.akmcp import MCP

MCP_NAME = "Agent Kernel FastMCP Instance"


@pytest.fixture(autouse=True)
def reset_mcp_state():
    """MCP keeps its FastMCP instance in class state; restore it so tests don't leak into each other."""
    saved = (MCP._fastmcp, MCP._built, dict(MCP._executors))
    MCP._fastmcp = None
    MCP._built = False
    MCP._executors = {}
    try:
        yield
    finally:
        MCP._fastmcp, MCP._built, MCP._executors = saved[0], saved[1], saved[2]


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
    the format label travels in MCP's own `_meta` slot rather than an Agent Kernel envelope.
    """

    @pytest.mark.asyncio
    async def test_labelled_reply_returns_a_tool_result_with_meta(self):
        from unittest.mock import AsyncMock, patch

        from fastmcp.tools.tool import ToolResult

        from agentkernel.api.mcp.akmcp import MCP
        from agentkernel.core.model import AgentReplyAny

        content = {"version": "v1.0", "createSurface": {"surfaceId": "s1"}}
        reply = AgentReplyAny(content=content, media_type="application/a2ui+json")

        with patch("agentkernel.api.mcp.akmcp.AgentService") as service_cls:
            service_cls.return_value.run_multi = AsyncMock(return_value=reply)
            result = await MCP.Executor("a").execute("s1", "hi", AsyncMock())

        assert isinstance(result, ToolResult)
        assert result.structured_content == content
        assert result.meta == {"media_type": "application/a2ui+json"}

    @pytest.mark.asyncio
    async def test_unlabelled_structured_reply_still_returns_its_string(self):
        from unittest.mock import AsyncMock, patch

        from agentkernel.api.mcp.akmcp import MCP
        from agentkernel.core.model import AgentReplyAny

        with patch("agentkernel.api.mcp.akmcp.AgentService") as service_cls:
            service_cls.return_value.run_multi = AsyncMock(return_value=AgentReplyAny(content={"a": 1}))
            result = await MCP.Executor("a").execute("s1", "hi", AsyncMock())

        assert result == '{"a": 1}'

    @pytest.mark.asyncio
    async def test_text_reply_returns_its_text(self):
        from unittest.mock import AsyncMock, patch

        from agentkernel.api.mcp.akmcp import MCP
        from agentkernel.core.model import AgentReplyText

        with patch("agentkernel.api.mcp.akmcp.AgentService") as service_cls:
            service_cls.return_value.run_multi = AsyncMock(return_value=AgentReplyText(response="hello"))
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

        with patch("agentkernel.api.mcp.akmcp.AgentService") as service_cls:
            service_cls.return_value.run_multi = AsyncMock(return_value=reply)
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

        with patch("agentkernel.api.mcp.akmcp.AgentService") as service_cls:
            service_cls.return_value.run_multi = AsyncMock(return_value=reply)
            async with Client(server) as client:
                result = await client.call_tool("a", {"session_id": "s1", "prompt": "hi"})

        assert result.structured_content == {"result": content}
        assert result.data == content
        assert result.meta["media_type"] == "application/a2ui+json"

    @pytest.mark.asyncio
    async def test_a_non_text_reply_returns_the_string_it_always_did(self):
        """`run_multi` replaced `AgentService.run`, whose mapping sent every other reply here."""
        from unittest.mock import AsyncMock, patch

        from agentkernel.api.mcp.akmcp import MCP
        from agentkernel.core.model import AgentReplyImage

        with patch("agentkernel.api.mcp.akmcp.AgentService") as service_cls:
            service_cls.return_value.run_multi = AsyncMock(return_value=AgentReplyImage(response="here it is", name="chart.png", image_data="aGk="))
            result = await MCP.Executor("a").execute("s1", "hi", AsyncMock())

        assert result == "Non-text reply given"
