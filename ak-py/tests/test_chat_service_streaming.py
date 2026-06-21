import pytest

from agentkernel.core.chat_service import ChatService
from agentkernel.core.model import BaseChatRequest, StreamChunk


class _FakeService:
    def __init__(self, chunks):
        self._chunks = chunks
        self.received_requests = None

    async def stream_multi(self, requests):
        self.received_requests = requests
        for chunk in self._chunks:
            yield chunk


class _FakeHandler:
    def __init__(self, service):
        self.service = service
        self.initialized_with = None

    def initialize(self, session_id, agent):
        self.initialized_with = (session_id, agent)

    async def run_stream_async(self, requests):
        async for chunk in self.service.stream_multi(requests):
            yield chunk

    def run_stream_sync(self, requests):
        import asyncio

        async def _collect():
            chunks = []
            async for chunk in self.service.stream_multi(requests):
                chunks.append(chunk)
            return chunks

        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                asyncio.set_event_loop(asyncio.new_event_loop())
                return asyncio.run(_collect())
            else:
                return loop.run_until_complete(_collect())
        except RuntimeError:
            return asyncio.run(_collect())


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
        '{"delta":"Hello","done":false}',
        '{"done":true,"session_id":"session-1"}',
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
        'data: {"delta":"Hello","done":false}\n\n',
        'data: {"done":true,"session_id":"session-1"}\n\n',
    ]


def test_process_stream_chat_sync_yields_chunks(monkeypatch):
    from agentkernel.core.model import BaseRunRequest

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
        '{"delta":"Hello","done":false}',
        '{"done":true,"session_id":"session-1"}',
    ]
