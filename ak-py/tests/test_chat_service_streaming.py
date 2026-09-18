import pytest

from agentkernel.core.chat_service import AgentHandler, ChatService
from agentkernel.core.model import BaseChatRequest, BaseRunRequest, StreamChunk


class _FakeService:
    def __init__(self, chunks):
        self._chunks = chunks
        self.received_requests = None

    async def stream_multi(self, requests, acting_user_id=None):
        self.received_requests = requests
        for chunk in self._chunks:
            yield chunk


class _FakeHandler:
    def __init__(self, service):
        self.service = service
        self.initialized_with = None

    def initialize(self, session_id, agent):
        self.initialized_with = (session_id, agent)

    async def run_stream_async(self, requests, acting_user_id=None):
        async for chunk in self.service.stream_multi(requests, acting_user_id=acting_user_id):
            yield chunk

    def run_stream_sync(self, requests, acting_user_id=None):
        from agentkernel.core.util.async_bridge import iterate_async_sync

        return iterate_async_sync(self.service.stream_multi(requests, acting_user_id=acting_user_id))


@pytest.mark.asyncio
async def test_process_stream_chat_async_defaults_to_json(monkeypatch):
    chunks = [StreamChunk(delta="Hello"), StreamChunk(done=True, session_id="session-1")]
    fake_service = _FakeService(chunks)
    fake_handler = _FakeHandler(fake_service)

    async def fake_from_base_request_async(req):
        return ["request-1"]

    monkeypatch.setattr("agentkernel.core.chat_service.RequestBuilder.from_base_request_async", fake_from_base_request_async)
    monkeypatch.setattr("agentkernel.core.chat_service.AgentHandler", lambda: fake_handler)

    service = ChatService()
    req = BaseChatRequest(prompt="Hi", session_id="session-1", agent="test-agent")

    gen = await service.process_stream_chat_async(req=req)
    payloads = [payload async for payload in gen]

    assert fake_handler.initialized_with == ("session-1", "test-agent")
    assert fake_service.received_requests == ["request-1"]
    assert payloads == [
        '{"delta": "Hello", "done": false, "session_id": "session-1"}',
        '{"done": true, "session_id": "session-1"}',
    ]


@pytest.mark.asyncio
async def test_process_stream_chat_async_can_return_sse_frames(monkeypatch):
    chunks = [StreamChunk(delta="Hello"), StreamChunk(done=True, session_id="session-1")]
    fake_service = _FakeService(chunks)
    fake_handler = _FakeHandler(fake_service)

    async def fake_from_base_request_async(req):
        return ["request-1"]

    monkeypatch.setattr("agentkernel.core.chat_service.RequestBuilder.from_base_request_async", fake_from_base_request_async)
    monkeypatch.setattr("agentkernel.core.chat_service.AgentHandler", lambda: fake_handler)

    service = ChatService()
    req = BaseChatRequest(prompt="Hi", session_id="session-1", agent="test-agent")

    gen = await service.process_stream_chat_async(req=req, sse_format=True)
    payloads = [payload async for payload in gen]

    assert payloads == [
        'data: {"delta": "Hello", "done": false, "session_id": "session-1"}\n\n',
        'data: {"done": true, "session_id": "session-1"}\n\n',
    ]


def test_process_stream_chat_sync_raises_immediately_on_missing_session_id():
    service = ChatService()
    req = BaseRunRequest(prompt="Hi", session_id=None, agent="test-agent")

    with pytest.raises(ValueError, match="session_id"):
        service.process_stream_chat_sync(req=req)


def test_process_stream_chat_sync_raises_immediately_on_missing_prompt():
    service = ChatService()
    req = BaseRunRequest(prompt="", session_id="session-1", agent="test-agent")

    with pytest.raises(ValueError, match="prompt"):
        service.process_stream_chat_sync(req=req)


def test_process_stream_chat_sync_yields_chunks(monkeypatch):
    chunks = [StreamChunk(delta="Hello"), StreamChunk(done=True, session_id="session-1")]
    fake_service = _FakeService(chunks)
    fake_handler = _FakeHandler(fake_service)

    def fake_from_base_request_sync(req):
        return ["request-1"]

    monkeypatch.setattr("agentkernel.core.chat_service.RequestBuilder.from_base_request_sync", fake_from_base_request_sync)
    monkeypatch.setattr("agentkernel.core.chat_service.AgentHandler", lambda: fake_handler)

    service = ChatService()
    req = BaseRunRequest(prompt="Hi", session_id="session-1", agent="test-agent")

    collected = list(service.process_stream_chat_sync(req=req))

    assert fake_handler.initialized_with == ("session-1", "test-agent")
    assert collected == [
        '{"delta": "Hello", "done": false, "session_id": "session-1"}',
        '{"done": true, "session_id": "session-1"}',
    ]


class _StreamingAgentService:
    """Stands in for AgentService so the real AgentHandler bridge is the thing under test."""

    def __init__(self, stream_multi):
        self._stream_multi = stream_multi

    def ensure_agent_available(self, agent):
        pass

    def select(self, session_id, agent):
        pass

    def get_response_session_id(self, session_id):
        return session_id

    def stream_multi(self, requests, acting_user_id=None):
        return self._stream_multi(requests, acting_user_id)


def _install_agent_service(monkeypatch, stream_multi):
    """Point ChatService's AgentHandler at a fake AgentService and skip request building."""
    monkeypatch.setattr("agentkernel.core.chat_service.RequestBuilder.from_base_request_sync", lambda req: ["request-1"])
    monkeypatch.setattr("agentkernel.core.chat_service.AgentService", lambda: _StreamingAgentService(stream_multi))


def test_run_stream_sync_hands_over_each_chunk_before_the_next_is_produced():
    """The sync bridge streams: a buffering one could not interleave these."""
    timeline = []

    async def _stream_multi(requests, acting_user_id=None):
        for index in range(3):
            timeline.append(f"produced-{index}")
            yield StreamChunk(delta=str(index))

    handler = AgentHandler()
    handler.service = _StreamingAgentService(_stream_multi)

    for chunk in handler.run_stream_sync(["request-1"]):
        timeline.append(f"consumed-{chunk.delta}")

    assert timeline == ["produced-0", "consumed-0", "produced-1", "consumed-1", "produced-2", "consumed-2"]


def test_process_stream_chat_sync_streams_chunks_as_the_run_produces_them(monkeypatch):
    timeline = []

    async def _stream_multi(requests, acting_user_id=None):
        for index in range(2):
            timeline.append(f"produced-{index}")
            yield StreamChunk(delta=str(index))
        timeline.append("produced-done")
        yield StreamChunk(done=True)

    _install_agent_service(monkeypatch, _stream_multi)
    service = ChatService()
    req = BaseRunRequest(prompt="Hi", session_id="session-1", agent="test-agent")

    for payload in service.process_stream_chat_sync(req=req):
        timeline.append(f"consumed-{payload}")

    assert timeline == [
        "produced-0",
        'consumed-{"delta": "0", "done": false, "session_id": "session-1"}',
        "produced-1",
        'consumed-{"delta": "1", "done": false, "session_id": "session-1"}',
        "produced-done",
        'consumed-{"done": true, "session_id": "session-1"}',
    ]


def test_process_stream_chat_sync_reports_a_mid_run_failure_after_the_chunks_already_sent(monkeypatch):
    """Error timing moved with the buffering: chunks are on the wire before the run raises."""

    async def _stream_multi(requests, acting_user_id=None):
        yield StreamChunk(delta="par")
        raise RuntimeError("stream blew up")

    _install_agent_service(monkeypatch, _stream_multi)
    service = ChatService()
    req = BaseRunRequest(prompt="Hi", session_id="session-1", agent="test-agent")

    collected = list(service.process_stream_chat_sync(req=req))

    assert collected == [
        '{"delta": "par", "done": false, "session_id": "session-1"}',
        '{"done": true, "error": "stream blew up", "session_id": "session-1"}',
    ]


def test_execute_stream_sync_closes_its_inner_iterator_by_contract(monkeypatch):
    """Abandoning the stream must close the run because the wrapper closes it, not because
    CPython happened to collect it.

    A plain ``for`` does not close its iterator when ``GeneratorExit`` unwinds the wrapper's
    frame; today's teardown rides on the refcount finalizer instead. Keeping a reference to the
    inner iterator here is what tells the two apart: it cannot be collected, so if the teardown
    still runs, the wrapper is the one that ran it.
    """
    torn_down = []

    def _inner():
        try:
            yield StreamChunk(delta="a")
            yield StreamChunk(delta="b")  # pragma: no cover - the consumer stops before this
        finally:
            torn_down.append("closed")

    held = _inner()  # outlives the wrapper, so nothing but the wrapper can close it

    monkeypatch.setattr(
        "agentkernel.core.chat_service.AgentHandler.run_stream_sync",
        lambda self, requests, acting_user_id=None: held,
    )
    _install_agent_service(monkeypatch, None)
    monkeypatch.setattr("agentkernel.core.chat_service.ChatService.prepare_agent_handler", lambda self, session_id, agent: AgentHandler())

    stream = ChatService().execute_stream_sync(BaseRunRequest(prompt="Hi", session_id="session-1", agent="test-agent"))
    next(stream)
    stream.close()

    assert torn_down == ["closed"], "the wrapper left the inner iterator's teardown to the garbage collector"


def test_process_stream_chat_sync_closes_its_inner_iterator_by_contract(monkeypatch):
    """The same contract one wrapper further out (see the test above for why the reference)."""
    torn_down = []

    def _inner():
        try:
            yield StreamChunk(delta="a")
            yield StreamChunk(delta="b")  # pragma: no cover - the consumer stops before this
        finally:
            torn_down.append("closed")

    held = _inner()

    monkeypatch.setattr("agentkernel.core.chat_service.ChatService.execute_stream_sync", lambda self, req, requests=None: held)

    stream = ChatService().process_stream_chat_sync(req=BaseRunRequest(prompt="Hi", session_id="session-1", agent="test-agent"))
    next(stream)
    stream.close()

    assert torn_down == ["closed"], "the wrapper left the inner iterator's teardown to the garbage collector"
