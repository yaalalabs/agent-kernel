from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentkernel.core.base import Agent, Runner
from agentkernel.core.chat_service import ACTING_USER_CACHE_KEY, ChatService
from agentkernel.core.config import AKConfig
from agentkernel.core.model import (
    AgentReplyText,
    AgentRequestAny,
    AgentRequestImage,
    AgentRequestText,
    BaseChatRequest,
    BaseRunRequest,
    StreamChunk,
)
from agentkernel.core.runtime import Runtime

ACTING_USER_AGENT = "acting-user-agent"


def _mock_handler(reply=None):
    """Build a mocked AgentHandler whose run methods return a fixed reply."""
    handler = MagicMock()
    handler.get_response_session_id.side_effect = lambda sid: sid
    if reply is not None:
        handler.run_async = AsyncMock(return_value=reply)
        handler.run_sync.return_value = reply
    return handler


def _stream_handler(chunks):
    """Build a mocked AgentHandler that streams the given chunks."""
    handler = MagicMock()
    handler.get_response_session_id.side_effect = lambda sid: sid

    async def _achunks(requests):
        for chunk in chunks:
            yield chunk

    handler.run_stream_async.side_effect = _achunks
    handler.run_stream_sync.return_value = list(chunks)
    return handler


class TestExecute:
    @pytest.mark.asyncio
    async def test_returns_typed_reply_and_session_id(self):
        reply = AgentReplyText(response="agent says hi")
        handler = _mock_handler(reply)
        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            service = ChatService()
            result, session_id = await service.execute(BaseRunRequest(prompt="hi", session_id="s1", agent="a1"))
        assert result is reply
        assert session_id == "s1"
        handler.initialize.assert_called_once_with("s1", "a1")
        built = handler.run_async.call_args.args[0]
        assert isinstance(built[0], AgentRequestText)
        assert built[0].prompt == "hi"

    @pytest.mark.asyncio
    async def test_prebuilt_requests_skip_request_builder(self):
        prebuilt = [AgentRequestImage(image_data="aW1n", name="pic.png", mime_type="image/png"), AgentRequestAny(name="body", content={"k": "v"})]
        handler = _mock_handler(AgentReplyText(response="ok"))

        async def _fail(req):
            raise AssertionError("RequestBuilder must not run on the prebuilt path")

        with patch("agentkernel.core.chat_service.RequestBuilder.from_base_request_async", _fail):
            with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
                service = ChatService()
                # prompt is optional on the prebuilt path (attachment-only message)
                result, _ = await service.execute(BaseChatRequest(prompt="", session_id="s1"), requests=prebuilt)
        assert str(result) == "ok"
        assert handler.run_async.call_args.args[0] is prebuilt

    @pytest.mark.asyncio
    async def test_missing_session_id_raises(self):
        service = ChatService()
        with pytest.raises(ValueError, match="session_id"):
            await service.execute(BaseChatRequest(prompt="hi", session_id=None))

    @pytest.mark.asyncio
    async def test_built_path_requires_prompt(self):
        service = ChatService()
        with pytest.raises(ValueError, match="prompt"):
            await service.execute(BaseChatRequest(prompt="", session_id="s1"))

    @pytest.mark.asyncio
    async def test_empty_prebuilt_list_raises(self):
        service = ChatService()
        with pytest.raises(ValueError, match="requests"):
            await service.execute(BaseChatRequest(prompt="hi", session_id="s1"), requests=[])

    @pytest.mark.asyncio
    async def test_no_agent_value_error_propagates(self):
        handler = _mock_handler()
        handler.initialize.side_effect = ValueError("No agent available")
        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            service = ChatService()
            with pytest.raises(ValueError, match="No agent available"):
                await service.execute(BaseRunRequest(prompt="hi", session_id="s1"))

    @pytest.mark.asyncio
    async def test_handler_exceptions_propagate_unmodified(self):
        handler = _mock_handler()
        handler.run_async = AsyncMock(side_effect=RuntimeError("agent blew up"))
        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            service = ChatService()
            with pytest.raises(RuntimeError, match="agent blew up"):
                await service.execute(BaseRunRequest(prompt="hi", session_id="s1"))


class TestExecuteSync:
    def test_returns_typed_reply_and_session_id(self):
        reply = AgentReplyText(response="agent says hi")
        handler = _mock_handler(reply)
        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            service = ChatService()
            result, session_id = service.execute_sync(BaseRunRequest(prompt="hi", session_id="s1"))
        assert result is reply
        assert session_id == "s1"

    def test_prebuilt_requests_skip_request_builder(self):
        prebuilt = [AgentRequestText(prompt="from the platform")]
        handler = _mock_handler(AgentReplyText(response="ok"))

        def _fail(req):
            raise AssertionError("RequestBuilder must not run on the prebuilt path")

        with patch("agentkernel.core.chat_service.RequestBuilder.from_base_request_sync", _fail):
            with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
                service = ChatService()
                service.execute_sync(BaseRunRequest(prompt="", session_id="s1"), requests=prebuilt)
        assert handler.run_sync.call_args.args[0] is prebuilt


class TestExecuteStream:
    @pytest.mark.asyncio
    async def test_yields_raw_stream_chunks(self):
        chunks = [StreamChunk(delta="Hel"), StreamChunk(delta="lo"), StreamChunk(done=True)]
        handler = _stream_handler(chunks)
        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            service = ChatService()
            gen = await service.execute_stream(BaseRunRequest(prompt="hi", session_id="s1"))
            collected = [chunk async for chunk in gen]
        assert collected == chunks
        assert all(isinstance(chunk, StreamChunk) for chunk in collected)

    @pytest.mark.asyncio
    async def test_invalid_input_raises_at_call_time(self):
        service = ChatService()
        with pytest.raises(ValueError, match="session_id"):
            await service.execute_stream(BaseRunRequest(prompt="hi", session_id=None))

    @pytest.mark.asyncio
    async def test_in_stream_exception_becomes_error_chunk(self):
        async def _failing(requests):
            yield StreamChunk(delta="par")
            raise RuntimeError("stream blew up")

        handler = MagicMock()
        handler.get_response_session_id.side_effect = lambda sid: sid
        handler.run_stream_async.side_effect = _failing
        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            service = ChatService()
            gen = await service.execute_stream(BaseRunRequest(prompt="hi", session_id="s1"))
            collected = [chunk async for chunk in gen]
        assert collected[0].delta == "par"
        assert collected[-1].error == "stream blew up"
        assert collected[-1].done is True


class TestExecuteStreamSync:
    def test_yields_raw_stream_chunks(self):
        chunks = [StreamChunk(delta="ok"), StreamChunk(done=True)]
        handler = _stream_handler(chunks)
        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            service = ChatService()
            collected = list(service.execute_stream_sync(BaseRunRequest(prompt="hi", session_id="s1")))
        assert collected == chunks

    def test_in_stream_exception_becomes_error_chunk(self):
        def _failing(requests):
            yield StreamChunk(delta="par")
            raise RuntimeError("stream blew up")

        handler = MagicMock()
        handler.get_response_session_id.side_effect = lambda sid: sid
        handler.run_stream_sync.side_effect = _failing
        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            service = ChatService()
            collected = list(service.execute_stream_sync(BaseRunRequest(prompt="hi", session_id="s1")))
        assert collected[-1].error == "stream blew up"
        assert collected[-1].done is True


class TestProcessWrappers:
    """The process_* wrappers keep their wire behavior on top of the core."""

    def test_process_chat_request_success_tuple(self):
        handler = _mock_handler(AgentReplyText(response="agent says hi"))
        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            service = ChatService()
            status, body = service.process_chat_request(BaseRunRequest(prompt="hi", session_id="s1"))
        assert status == 200
        assert body == {"result": "agent says hi", "session_id": "s1"}

    def test_process_chat_request_validation_maps_to_400(self):
        service = ChatService()
        status, body = service.process_chat_request(BaseRunRequest(prompt="", session_id="s1"))
        assert status == 400
        assert "prompt" in body["error"]
        assert body["session_id"] == "s1"

    def test_process_chat_request_failure_maps_to_500_with_session_id(self):
        handler = _mock_handler()
        handler.run_sync.side_effect = RuntimeError("agent blew up")
        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            service = ChatService()
            status, body = service.process_chat_request(BaseRunRequest(prompt="hi", session_id="s1"))
        assert status == 500
        assert body["error"] == "agent blew up"
        assert body["session_id"] == "s1"

    @pytest.mark.asyncio
    async def test_process_async_chat_request_success_tuple(self):
        handler = _mock_handler(AgentReplyText(response="agent says hi"))
        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            service = ChatService()
            status, body = await service.process_async_chat_request(BaseRunRequest(prompt="hi", session_id="s1"))
        assert status == 200
        assert body == {"result": "agent says hi", "session_id": "s1"}

    @pytest.mark.asyncio
    async def test_process_async_chat_request_no_agent_maps_to_400(self):
        handler = _mock_handler()
        handler.initialize.side_effect = ValueError("No agent available")
        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            service = ChatService()
            status, body = await service.process_async_chat_request(BaseRunRequest(prompt="hi", session_id="s1"))
        assert status == 400
        assert body["error"] == "No agent available"


class _ActingUserRunner(Runner):
    """Records the acting user visible from inside the run, the way a hook or tool would read it."""

    def __init__(self):
        super().__init__("ActingUserRunner")
        self.seen: list = []

    async def run(self, agent, session, requests):
        self.seen.append(session.get_volatile_cache().get(ACTING_USER_CACHE_KEY))
        return AgentReplyText(response="ok")

    async def stream(self, agent, session, requests):
        self.seen.append(session.get_volatile_cache().get(ACTING_USER_CACHE_KEY))
        yield "ok"


class _ActingUserAgent(Agent):
    def __init__(self, runner: _ActingUserRunner):
        super().__init__(ACTING_USER_AGENT, runner)

    def get_description(self) -> str:
        return "Acting-user propagation test agent"

    def get_a2a_card(self):
        return None

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


class TestActingUserPropagation:
    """A run whose request carries user_id exposes it in the session volatile cache, so hooks and
    tools can attribute work to the caller (#629 Phase 2)."""

    @pytest.fixture
    def runner(self, monkeypatch):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        AKConfig._reset()
        capturing_runner = _ActingUserRunner()
        agent = _ActingUserAgent(capturing_runner)
        Runtime.current().register(agent)
        yield capturing_runner
        Runtime.current().deregister(agent)
        AKConfig._reset()

    def _request(self, session_id: str, user_id=None) -> BaseRunRequest:
        return BaseRunRequest(prompt="hi", session_id=session_id, agent=ACTING_USER_AGENT, user_id=user_id)

    @pytest.mark.asyncio
    async def test_execute_exposes_the_acting_user(self, runner):
        await ChatService().execute(self._request("s-acting-1", user_id="u-1"))
        assert runner.seen == ["u-1"]

    def test_execute_sync_exposes_the_acting_user(self, runner):
        ChatService().execute_sync(self._request("s-acting-2", user_id="u-2"))
        assert runner.seen == ["u-2"]

    @pytest.mark.asyncio
    async def test_execute_stream_exposes_the_acting_user(self, runner):
        chunks = await ChatService().execute_stream(self._request("s-acting-3", user_id="u-3"))
        [chunk async for chunk in chunks]
        assert runner.seen == ["u-3"]

    def test_execute_stream_sync_exposes_the_acting_user(self, runner):
        list(ChatService().execute_stream_sync(self._request("s-acting-4", user_id="u-4")))
        assert runner.seen == ["u-4"]

    @pytest.mark.asyncio
    async def test_request_without_a_user_id_publishes_nothing(self, runner):
        await ChatService().execute(self._request("s-acting-5"))
        assert runner.seen == [None]

    @pytest.mark.asyncio
    async def test_key_does_not_survive_into_the_next_run_of_the_same_session(self, runner):
        """Runtime clears the volatile cache when a run ends, so the acting user is per-run and
        never attributed to a later, unauthenticated request on the same session."""
        service = ChatService()
        await service.execute(self._request("s-acting-6", user_id="u-6"))
        await service.execute(self._request("s-acting-6"))
        assert runner.seen == ["u-6", None]
