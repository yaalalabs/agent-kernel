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
