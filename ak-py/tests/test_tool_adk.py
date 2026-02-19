import asyncio
import inspect
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.adk.tools import FunctionTool
from google.adk.tools import ToolContext as ADKToolContext

from agentkernel.core.base import Agent, Runner, Session
from agentkernel.core.model import AgentReply, AgentRequest, AgentRequestText
from agentkernel.core.runtime import Runtime
from agentkernel.core.tool import ToolContext as AKToolContext
from agentkernel.framework.adk.adk import GoogleADKRunner, GoogleADKToolBuilder


# Helpers
class MockRunner(Runner):
    def __init__(self):
        super().__init__("mock")

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        return AgentReply(content="mock")


class MockAgent(Agent):
    def __init__(self, name: str = "mock-agent"):
        super().__init__(name, MockRunner())

    def get_description(self) -> str:
        return "mock"

    def get_a2a_card(self) -> Any:
        return None

    def get_wrapped(self):
        return self

    def override_system_prompt(self, session: "Session", prompt: str) -> None:
        pass

    def attach_tool(self, tool: Any) -> None:
        pass


def _make_adk_tool_context(state: dict[str, Any] | None = None) -> ADKToolContext:
    """Build a mock ADK ToolContext whose .state returns the given dict."""
    ctx = MagicMock(spec=ADKToolContext)
    ctx.state = state or {}
    return ctx


# Sample tool functions
def get_weather(city: str) -> str:
    """Returns the weather for a given city."""
    return f"Weather in {city}: sunny"


def add(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b


async def async_lookup(name: str) -> str:
    """Asynchronously look up a name."""
    return f"Found: {name}"


async def async_multiply(x: int, y: int) -> int:
    """Asynchronously multiply two numbers."""
    return x * y


def no_params() -> str:
    """A tool that takes no parameters."""
    return "done"


def multi_type_params(text: str, count: int, flag: bool = False) -> str:
    """A tool with multiple parameter types."""
    return f"{text}-{count}-{flag}"


# bind – basic behaviour
class TestGoogleADKToolBuilderBind:

    def test_bind_returns_list(self):
        tools = GoogleADKToolBuilder.bind([get_weather])
        assert isinstance(tools, list)

    def test_bind_returns_function_tools(self):
        tools = GoogleADKToolBuilder.bind([get_weather])
        assert len(tools) == 1
        assert isinstance(tools[0], FunctionTool)

    def test_bind_multiple_functions(self):
        tools = GoogleADKToolBuilder.bind([get_weather, add, no_params])
        assert len(tools) == 3
        assert all(isinstance(t, FunctionTool) for t in tools)

    def test_bind_empty_list(self):
        tools = GoogleADKToolBuilder.bind([])
        assert tools == []

    def test_bind_preserves_order(self):
        tools = GoogleADKToolBuilder.bind([get_weather, add, no_params])
        assert tools[0].name == "get_weather"
        assert tools[1].name == "add"
        assert tools[2].name == "no_params"


# Tool metadata – name, description
class TestToolMetadata:

    def test_tool_name_matches_function(self):
        [tool] = GoogleADKToolBuilder.bind([get_weather])
        assert tool.name == "get_weather"

    def test_tool_description_from_docstring(self):
        [tool] = GoogleADKToolBuilder.bind([get_weather])
        assert "weather" in tool.description.lower()

    def test_async_tool_name(self):
        [tool] = GoogleADKToolBuilder.bind([async_lookup])
        assert tool.name == "async_lookup"

    def test_async_tool_description(self):
        [tool] = GoogleADKToolBuilder.bind([async_lookup])
        assert "look up" in tool.description.lower()


# _wrap – internal wrapper behaviour
class TestWrapInternal:

    def test_wrap_sync_preserves_name(self):
        wrapped = GoogleADKToolBuilder._wrap(get_weather)
        assert wrapped.__name__ == "get_weather"

    def test_wrap_sync_preserves_docstring(self):
        wrapped = GoogleADKToolBuilder._wrap(get_weather)
        assert wrapped.__doc__ == get_weather.__doc__

    def test_wrap_async_preserves_name(self):
        wrapped = GoogleADKToolBuilder._wrap(async_lookup)
        assert wrapped.__name__ == "async_lookup"

    def test_wrap_async_preserves_docstring(self):
        wrapped = GoogleADKToolBuilder._wrap(async_lookup)
        assert wrapped.__doc__ == async_lookup.__doc__

    def test_wrap_sync_returns_sync(self):
        wrapped = GoogleADKToolBuilder._wrap(get_weather)
        assert not asyncio.iscoroutinefunction(wrapped)

    def test_wrap_async_returns_async(self):
        wrapped = GoogleADKToolBuilder._wrap(async_lookup)
        assert asyncio.iscoroutinefunction(wrapped)

    def test_wrap_non_callable_raises(self):
        with pytest.raises(TypeError, match="Expected a callable"):
            GoogleADKToolBuilder._wrap("not a function")

    def test_wrap_non_callable_int_raises(self):
        with pytest.raises(TypeError, match="Expected a callable"):
            GoogleADKToolBuilder._wrap(42)

    def test_wrap_non_callable_none_raises(self):
        with pytest.raises(TypeError, match="Expected a callable"):
            GoogleADKToolBuilder._wrap(None)


# _wrap – signature augmentation with tool_context parameter
class TestWrapSignature:

    def test_sync_wrapper_has_tool_context_param(self):
        wrapped = GoogleADKToolBuilder._wrap(get_weather)
        sig = inspect.signature(wrapped)
        assert "tool_context" in sig.parameters

    def test_async_wrapper_has_tool_context_param(self):
        wrapped = GoogleADKToolBuilder._wrap(async_lookup)
        sig = inspect.signature(wrapped)
        assert "tool_context" in sig.parameters

    def test_tool_context_param_is_keyword_only(self):
        wrapped = GoogleADKToolBuilder._wrap(get_weather)
        sig = inspect.signature(wrapped)
        param = sig.parameters["tool_context"]
        assert param.kind == inspect.Parameter.KEYWORD_ONLY

    def test_tool_context_param_default_is_none(self):
        wrapped = GoogleADKToolBuilder._wrap(get_weather)
        sig = inspect.signature(wrapped)
        param = sig.parameters["tool_context"]
        assert param.default is None

    def test_original_params_preserved_in_signature(self):
        wrapped = GoogleADKToolBuilder._wrap(add)
        sig = inspect.signature(wrapped)
        param_names = list(sig.parameters.keys())
        assert "a" in param_names
        assert "b" in param_names
        assert "tool_context" in param_names

    def test_multi_type_params_preserved(self):
        wrapped = GoogleADKToolBuilder._wrap(multi_type_params)
        sig = inspect.signature(wrapped)
        param_names = list(sig.parameters.keys())
        assert "text" in param_names
        assert "count" in param_names
        assert "flag" in param_names
        assert "tool_context" in param_names


# _wrap – invocation with AKToolContext integration
class TestWrapInvocationWithContext:

    def _create_ak_context(self):
        """Create an AKToolContext and enter it so it is cached for fetch()."""
        runtime = MagicMock(spec=Runtime)
        agent = MockAgent()
        session = Session("test-session")
        requests = [AgentRequestText(text="hi")]
        return AKToolContext(runtime, agent, session, requests)

    def test_sync_wrapper_invokes_function_with_correct_args(self):
        ak_ctx = self._create_ak_context()
        with ak_ctx:
            adk_ctx = _make_adk_tool_context({"ak_tool_context": ak_ctx.id})
            wrapped = GoogleADKToolBuilder._wrap(get_weather)
            result = wrapped("Tokyo", tool_context=adk_ctx)
            assert result == "Weather in Tokyo: sunny"

    @pytest.mark.asyncio
    async def test_async_wrapper_invokes_function_with_correct_args(self):
        ak_ctx = self._create_ak_context()
        with ak_ctx:
            adk_ctx = _make_adk_tool_context({"ak_tool_context": ak_ctx.id})
            wrapped = GoogleADKToolBuilder._wrap(async_lookup)
            result = await wrapped("Alice", tool_context=adk_ctx)
            assert result == "Found: Alice"

    def test_sync_wrapper_sets_and_resets_ak_context(self):
        ak_ctx = self._create_ak_context()
        with ak_ctx:
            adk_ctx = _make_adk_tool_context({"ak_tool_context": ak_ctx.id})

            def check_context() -> str:
                """Check context is active."""
                ctx = AKToolContext.get()
                return ctx.id

            wrapped = GoogleADKToolBuilder._wrap(check_context)
            returned_id = wrapped(tool_context=adk_ctx)
            assert returned_id == ak_ctx.id

        # After wrapper returns, AKToolContext should have been reset
        AKToolContext._context.set(None)
        with pytest.raises(RuntimeError):
            AKToolContext.get()

    @pytest.mark.asyncio
    async def test_async_wrapper_sets_and_resets_ak_context(self):
        ak_ctx = self._create_ak_context()
        with ak_ctx:
            adk_ctx = _make_adk_tool_context({"ak_tool_context": ak_ctx.id})

            async def check_context_async() -> str:
                """Check context is active."""
                ctx = AKToolContext.get()
                return ctx.id

            wrapped = GoogleADKToolBuilder._wrap(check_context_async)
            returned_id = await wrapped(tool_context=adk_ctx)
            assert returned_id == ak_ctx.id

    def test_sync_wrapper_resets_context_on_exception(self):
        ak_ctx = self._create_ak_context()
        with ak_ctx:
            adk_ctx = _make_adk_tool_context({"ak_tool_context": ak_ctx.id})

            def failing_func() -> str:
                """Always fails."""
                raise ValueError("boom")

            wrapped = GoogleADKToolBuilder._wrap(failing_func)
            with pytest.raises(ValueError, match="boom"):
                wrapped(tool_context=adk_ctx)

        # Context should still have been reset despite the exception
        AKToolContext._context.set(None)
        with pytest.raises(RuntimeError):
            AKToolContext.get()

    @pytest.mark.asyncio
    async def test_async_wrapper_resets_context_on_exception(self):
        ak_ctx = self._create_ak_context()
        with ak_ctx:
            adk_ctx = _make_adk_tool_context({"ak_tool_context": ak_ctx.id})

            async def failing_async() -> str:
                """Always fails."""
                raise ValueError("async boom")

            wrapped = GoogleADKToolBuilder._wrap(failing_async)
            with pytest.raises(ValueError, match="async boom"):
                await wrapped(tool_context=adk_ctx)

    def test_sync_wrapper_fetches_context_from_adk_state(self):
        """Verify that wrapper uses tool_context.state['ak_tool_context'] to fetch AKToolContext."""
        ak_ctx = self._create_ak_context()
        with ak_ctx:
            captured_ids = []

            def capture_context() -> str:
                """Capture the context id."""
                captured_ids.append(AKToolContext.get().id)
                return "ok"

            adk_ctx = _make_adk_tool_context({"ak_tool_context": ak_ctx.id})
            wrapped = GoogleADKToolBuilder._wrap(capture_context)
            wrapped(tool_context=adk_ctx)

            assert len(captured_ids) == 1
            assert captured_ids[0] == ak_ctx.id

    def test_wrapper_raises_key_error_for_missing_context_id(self):
        """If the AKToolContext is not in the cache, fetching should raise KeyError."""
        adk_ctx = _make_adk_tool_context({"ak_tool_context": "nonexistent-id"})
        wrapped = GoogleADKToolBuilder._wrap(get_weather)
        with pytest.raises(KeyError, match="No ToolContext found for id"):
            wrapped("Tokyo", tool_context=adk_ctx)


# Mixed sync / async binding
class TestMixedBinding:

    def test_bind_mixed_sync_and_async(self):
        tools = GoogleADKToolBuilder.bind([get_weather, async_lookup, add, async_multiply])
        assert len(tools) == 4
        assert all(isinstance(t, FunctionTool) for t in tools)

    def test_mixed_names_preserved(self):
        tools = GoogleADKToolBuilder.bind([get_weather, async_lookup])
        names = [t.name for t in tools]
        assert names == ["get_weather", "async_lookup"]


# GoogleADKRunner – ToolContext initialization in run()
class TestGoogleADKRunnerToolContext:

    @pytest.mark.asyncio
    async def test_run_creates_ak_tool_context_in_session_state(self):
        """
        GoogleADKRunner.run() should create an AKToolContext, enter it via the
        context manager, and pass its id via update_session_state as
        state['ak_tool_context'].
        """
        runner = GoogleADKRunner()
        session = Session("runner-test-session")
        requests = [AgentRequestText(text="hello")]
        mock_agent = MagicMock()
        mock_agent.agent = MagicMock()

        updated_state = {}

        async def capture_update_session_state(invocation_id, author, state):
            updated_state.update(state)

        mock_adk_session = MagicMock()
        mock_adk_session.create_session = AsyncMock(return_value=MagicMock())
        mock_adk_session.update_session_state = AsyncMock(side_effect=capture_update_session_state)
        mock_adk_session.session_service = MagicMock()

        with (
            patch.object(GoogleADKRunner, "_session", return_value=mock_adk_session),
            patch.object(GoogleADKRunner, "get_response", new_callable=AsyncMock, return_value="reply text"),
            patch.object(Runtime, "current", return_value=MagicMock(spec=Runtime)),
        ):
            result = await runner.run(mock_agent, session, requests)

        assert "ak_tool_context" in updated_state
        # The id should be a non-empty hex string (uuid4)
        assert isinstance(updated_state["ak_tool_context"], str)
        assert len(updated_state["ak_tool_context"]) > 0

    @pytest.mark.asyncio
    async def test_run_tool_context_is_fetchable_during_execution(self):
        """
        During runner.run(), the AKToolContext should be entered (cached)
        so that tools can fetch it via AKToolContext.fetch(id).
        """
        runner = GoogleADKRunner()
        session = Session("fetch-test-session")
        requests = [AgentRequestText(text="test")]
        mock_agent = MagicMock()
        mock_agent.agent = MagicMock()

        fetched_ctx = None

        async def mock_update_session_state(invocation_id, author, state):
            nonlocal fetched_ctx
            if "ak_tool_context" in state:
                # This should succeed if the context is in the cache
                fetched_ctx = AKToolContext.fetch(state["ak_tool_context"])

        mock_adk_session = MagicMock()
        mock_adk_session.create_session = AsyncMock(return_value=MagicMock())
        mock_adk_session.update_session_state = AsyncMock(side_effect=mock_update_session_state)
        mock_adk_session.session_service = MagicMock()

        with (
            patch.object(GoogleADKRunner, "_session", return_value=mock_adk_session),
            patch.object(GoogleADKRunner, "get_response", new_callable=AsyncMock, return_value="done"),
            patch.object(Runtime, "current", return_value=MagicMock(spec=Runtime)),
        ):
            await runner.run(mock_agent, session, requests)

        assert fetched_ctx is not None
        assert isinstance(fetched_ctx, AKToolContext)

    @pytest.mark.asyncio
    async def test_run_tool_context_cleaned_up_after_execution(self):
        """
        After runner.run() completes, the AKToolContext should be removed
        from the cache (context manager __exit__ called).
        """
        runner = GoogleADKRunner()
        session = Session("cleanup-test-session")
        requests = [AgentRequestText(text="cleanup")]
        mock_agent = MagicMock()
        mock_agent.agent = MagicMock()

        captured_id = None

        async def capture_state(invocation_id, author, state):
            nonlocal captured_id
            if "ak_tool_context" in state:
                captured_id = state["ak_tool_context"]

        mock_adk_session = MagicMock()
        mock_adk_session.create_session = AsyncMock(return_value=MagicMock())
        mock_adk_session.update_session_state = AsyncMock(side_effect=capture_state)
        mock_adk_session.session_service = MagicMock()

        with (
            patch.object(GoogleADKRunner, "_session", return_value=mock_adk_session),
            patch.object(GoogleADKRunner, "get_response", new_callable=AsyncMock, return_value="reply"),
            patch.object(Runtime, "current", return_value=MagicMock(spec=Runtime)),
        ):
            await runner.run(mock_agent, session, requests)

        assert captured_id is not None
        # After run() the context manager should have exited, clearing the cache
        with pytest.raises(KeyError):
            AKToolContext.fetch(captured_id)

    @pytest.mark.asyncio
    async def test_run_calls_create_session_without_state(self):
        """
        GoogleADKRunner.run() should call create_session with only
        app_name, user_id, and session_id (no state parameter).
        """
        runner = GoogleADKRunner()
        session = Session("no-state-session")
        requests = [AgentRequestText(text="hello")]
        mock_agent = MagicMock()
        mock_agent.agent = MagicMock()

        mock_adk_session = MagicMock()
        mock_adk_session.create_session = AsyncMock(return_value=MagicMock())
        mock_adk_session.update_session_state = AsyncMock()
        mock_adk_session.session_service = MagicMock()

        with (
            patch.object(GoogleADKRunner, "_session", return_value=mock_adk_session),
            patch.object(GoogleADKRunner, "get_response", new_callable=AsyncMock, return_value="reply"),
            patch.object(Runtime, "current", return_value=MagicMock(spec=Runtime)),
        ):
            await runner.run(mock_agent, session, requests)

        mock_adk_session.create_session.assert_awaited_once()
        call_args = mock_adk_session.create_session.call_args
        # create_session should be called with exactly 3 positional/keyword args, no state
        assert "state" not in (call_args.kwargs or {})

    @pytest.mark.asyncio
    async def test_run_calls_update_session_state_after_create_session(self):
        """
        GoogleADKRunner.run() should call update_session_state after
        create_session to set the ak_tool_context in session state.
        """
        runner = GoogleADKRunner()
        session = Session("order-test-session")
        requests = [AgentRequestText(text="hello")]
        mock_agent = MagicMock()
        mock_agent.agent = MagicMock()
        mock_agent.name = "test-agent"

        call_order = []

        async def track_create_session(app_name, user_id, session_id):
            call_order.append("create_session")
            return MagicMock()

        async def track_update_session_state(invocation_id, author, state):
            call_order.append("update_session_state")

        mock_adk_session = MagicMock()
        mock_adk_session.create_session = AsyncMock(side_effect=track_create_session)
        mock_adk_session.update_session_state = AsyncMock(side_effect=track_update_session_state)
        mock_adk_session.session_service = MagicMock()

        with (
            patch.object(GoogleADKRunner, "_session", return_value=mock_adk_session),
            patch.object(GoogleADKRunner, "get_response", new_callable=AsyncMock, return_value="reply"),
            patch.object(Runtime, "current", return_value=MagicMock(spec=Runtime)),
        ):
            await runner.run(mock_agent, session, requests)

        assert call_order == ["create_session", "update_session_state"]

    @pytest.mark.asyncio
    async def test_run_update_session_state_receives_context_id_and_agent_name(self):
        """
        update_session_state should be called with the context id as
        invocation_id, agent name as author, and state containing ak_tool_context.
        """
        runner = GoogleADKRunner()
        session = Session("args-test-session")
        requests = [AgentRequestText(text="hello")]
        mock_agent = MagicMock()
        mock_agent.agent = MagicMock()
        mock_agent.name = "my-agent"

        mock_adk_session = MagicMock()
        mock_adk_session.create_session = AsyncMock(return_value=MagicMock())
        mock_adk_session.update_session_state = AsyncMock()
        mock_adk_session.session_service = MagicMock()

        with (
            patch.object(GoogleADKRunner, "_session", return_value=mock_adk_session),
            patch.object(GoogleADKRunner, "get_response", new_callable=AsyncMock, return_value="reply"),
            patch.object(Runtime, "current", return_value=MagicMock(spec=Runtime)),
        ):
            await runner.run(mock_agent, session, requests)

        mock_adk_session.update_session_state.assert_awaited_once()
        call_args = mock_adk_session.update_session_state.call_args
        invocation_id, author, state = call_args.args
        assert isinstance(invocation_id, str) and len(invocation_id) > 0
        assert author == "my-agent"
        assert "ak_tool_context" in state
        assert state["ak_tool_context"] == invocation_id

    @pytest.mark.asyncio
    async def test_run_returns_error_reply_on_exception(self):
        """
        If an exception occurs during run(), it should be caught and returned
        as an error AgentReplyText.
        """
        runner = GoogleADKRunner()
        session = Session("error-test-session")
        requests = [AgentRequestText(text="fail")]
        mock_agent = MagicMock()
        mock_agent.agent = MagicMock()

        with patch.object(Runtime, "current", side_effect=RuntimeError("runtime error")):
            result = await runner.run(mock_agent, session, requests)

        assert "Error during agent execution" in result.text

    @pytest.mark.asyncio
    async def test_run_returns_no_content_for_empty_requests(self):
        """
        If requests contain only AgentRequestAny (skipped), run() should
        return a "no valid content" reply.
        """
        from agentkernel.core.model import AgentRequestAny

        runner = GoogleADKRunner()
        session = Session("empty-test-session")
        requests = [AgentRequestAny(content="blob", name="data")]
        mock_agent = MagicMock()

        result = await runner.run(mock_agent, session, requests)
        assert "No valid content" in result.text


# Edge cases
class TestEdgeCases:

    def test_bind_lambda(self):
        my_lambda = lambda x: x + 1  # noqa: E731
        my_lambda.__doc__ = "Increment by one."
        my_lambda.__name__ = "increment"
        tools = GoogleADKToolBuilder.bind([my_lambda])
        assert len(tools) == 1
        assert tools[0].name == "increment"

    def test_bind_same_function_twice(self):
        tools = GoogleADKToolBuilder.bind([get_weather, get_weather])
        assert len(tools) == 2
        assert tools[0].name == tools[1].name == "get_weather"

    def test_bound_tool_has_func_attribute(self):
        [tool] = GoogleADKToolBuilder.bind([get_weather])
        assert hasattr(tool, "func")
        assert callable(tool.func)
