"""
Tests for ToolContext and ToolBuilder base class.
"""

import asyncio
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch

import pytest

from agentkernel.core.base import Session
from agentkernel.core.runtime import Runtime
from agentkernel.core.tool import ToolBuilder, ToolContext

# ---------------------------------------------------------------------------
# ToolContext tests
# ---------------------------------------------------------------------------


class TestToolContext:
    def test_creation(self):
        runtime = MagicMock(spec=Runtime)
        session = Session("s1")
        ctx = ToolContext(runtime=runtime, session=session)
        assert ctx.runtime is runtime
        assert ctx.session is session

    def test_immutability(self):
        runtime = MagicMock(spec=Runtime)
        session = Session("s1")
        ctx = ToolContext(runtime=runtime, session=session)
        with pytest.raises(FrozenInstanceError):
            ctx.runtime = MagicMock()
        with pytest.raises(FrozenInstanceError):
            ctx.session = Session("s2")


# ---------------------------------------------------------------------------
# ToolBuilder._needs_tool_context tests
# ---------------------------------------------------------------------------


class TestNeedsToolContext:
    def test_no_context_param(self):
        def my_tool(city: str, units: str = "celsius") -> str:
            return city

        needs, name = ToolBuilder._needs_tool_context(my_tool)
        assert needs is False
        assert name is None

    def test_sync_with_context(self):
        def my_tool(city: str, ctx: ToolContext) -> str:
            return city

        needs, name = ToolBuilder._needs_tool_context(my_tool)
        assert needs is True
        assert name == "ctx"

    def test_async_with_context(self):
        async def my_tool(city: str, context: ToolContext) -> str:
            return city

        needs, name = ToolBuilder._needs_tool_context(my_tool)
        assert needs is True
        assert name == "context"

    def test_custom_param_name(self):
        def my_tool(city: str, my_special_ctx: ToolContext) -> str:
            return city

        needs, name = ToolBuilder._needs_tool_context(my_tool)
        assert needs is True
        assert name == "my_special_ctx"

    def test_multiple_params_with_context(self):
        def my_tool(city: str, units: str, tc: ToolContext, verbose: bool = False) -> str:
            return city

        needs, name = ToolBuilder._needs_tool_context(my_tool)
        assert needs is True
        assert name == "tc"

    def test_no_annotations(self):
        def my_tool(city, units):
            return city

        needs, name = ToolBuilder._needs_tool_context(my_tool)
        assert needs is False
        assert name is None


# ---------------------------------------------------------------------------
# ToolBuilder._wrap sync function tests
# ---------------------------------------------------------------------------


class TestWrapSync:
    def test_wrap_without_context_passthrough(self):
        def get_weather(city: str, units: str = "celsius") -> str:
            return f"Weather in {city} ({units})"

        wrapped = ToolBuilder._wrap(get_weather)
        # When no ToolContext param, the original function is returned
        assert wrapped is get_weather
        result = wrapped(city="London", units="fahrenheit")
        assert result == "Weather in London (fahrenheit)"

    def test_wrap_with_context_injection(self):
        def get_weather(city: str, ctx: ToolContext) -> str:
            return f"Weather in {city}, runtime={ctx.runtime is not None}"

        mock_runtime = MagicMock(spec=Runtime)
        mock_session = Session("test-session")

        with patch.object(Runtime, "current", return_value=mock_runtime):
            with patch.object(Session, "current", return_value=mock_session):
                wrapped = ToolBuilder._wrap(get_weather)
                assert wrapped is not get_weather
                assert not asyncio.iscoroutinefunction(wrapped)
                result = wrapped(city="Paris")
                assert "Weather in Paris" in result
                assert "runtime=True" in result

    def test_wrap_preserves_function_metadata(self):
        def get_weather(city: str, ctx: ToolContext) -> str:
            """Get weather for a city."""
            return city

        wrapped = ToolBuilder._wrap(get_weather)
        assert wrapped.__name__ == "get_weather"
        assert wrapped.__doc__ == "Get weather for a city."

    def test_wrap_non_callable_raises(self):
        with pytest.raises(TypeError, match="Expected a callable"):
            ToolBuilder._wrap("not a function")


# ---------------------------------------------------------------------------
# ToolBuilder._wrap async function tests
# ---------------------------------------------------------------------------


class TestWrapAsync:
    def test_wrap_async_without_context_passthrough(self):
        async def get_weather(city: str) -> str:
            return f"Weather in {city}"

        wrapped = ToolBuilder._wrap(get_weather)
        assert wrapped is get_weather

    @pytest.mark.asyncio
    async def test_wrap_async_with_context_injection(self):
        async def get_weather(city: str, ctx: ToolContext) -> str:
            return f"Weather in {city}, session={ctx.session.id}"

        mock_runtime = MagicMock(spec=Runtime)
        mock_session = Session("async-session")

        with patch.object(Runtime, "current", return_value=mock_runtime):
            with patch.object(Session, "current", return_value=mock_session):
                wrapped = ToolBuilder._wrap(get_weather)
                assert wrapped is not get_weather
                assert asyncio.iscoroutinefunction(wrapped)
                result = await wrapped(city="Tokyo")
                assert "Weather in Tokyo" in result
                assert "session=async-session" in result

    @pytest.mark.asyncio
    async def test_wrap_async_preserves_metadata(self):
        async def get_forecast(city: str, tc: ToolContext) -> str:
            """Get forecast for a city."""
            return city

        wrapped = ToolBuilder._wrap(get_forecast)
        assert wrapped.__name__ == "get_forecast"
        assert wrapped.__doc__ == "Get forecast for a city."
        assert asyncio.iscoroutinefunction(wrapped)


# ---------------------------------------------------------------------------
# ToolBuilder.bind raises NotImplementedError
# ---------------------------------------------------------------------------


class TestToolBuilderBind:
    def test_bind_raises(self):
        with pytest.raises(NotImplementedError):
            ToolBuilder.bind([lambda: None])
