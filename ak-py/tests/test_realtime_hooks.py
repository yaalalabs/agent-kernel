"""Pre-hooks and post-hooks on a realtime call (#927): the connection runs the agent's hooks on caller text and audio and on every output event."""

import asyncio
import base64
import json
import logging
import time

import pytest

from agentkernel import Agent, Runner, Session
from agentkernel.core.config import _GuardrailConfig, _GuardrailParamConfig
from agentkernel.core.event import AgentChanged, AudioDelta, Interrupt, MessageEnd, TextDelta
from agentkernel.core.hooks import PostHook, PreHook, StreamHalt
from agentkernel.core.model import AgentReplyText, AgentRequestText, AgentRequestVoice, StreamChunk
from agentkernel.core.realtime import RealtimeRunner
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.pipeline.envelope import QueueName
from agentkernel.pipeline.realtime_pool import RealtimeConnection, RealtimeConnectionPool
from agentkernel.pipeline.thread_runner import ThreadRunner
from agentkernel.pipeline.transport.base import QueueTransportFactory
from agentkernel.pipeline.transport.in_memory import InMemoryTransport

PCM_2S = base64.b64encode(b"\x00\x00" * 24000 * 2).decode()  # two seconds of edge-rate (24 kHz) audio


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    async def send_inline(send, *args):
        return send(*args)

    monkeypatch.setattr("agentkernel.pipeline.realtime_pool.asyncio.to_thread", send_inline)
    # System hooks are cached per process; a test that wants some installs them itself.
    monkeypatch.setattr(Runtime, "_system_pre_hooks", [])
    monkeypatch.setattr(Runtime, "_system_post_hooks", [])
    InMemoryTransport.reset()
    ThreadRunner.shutdown_event.clear()
    transport = InMemoryTransport()
    monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: transport))
    yield
    InMemoryTransport.reset()
    RealtimeConnectionPool.reset()
    ThreadRunner.shutdown_event.clear()


class _Runner(Runner):
    def __init__(self):
        super().__init__("test-runner")

    async def run(self, agent, session, requests):
        return AgentReplyText(response="ok")

    async def stream(self, agent, session, requests):
        raise NotImplementedError()
        yield


class _Adapter(RealtimeRunner):
    """Records what the pool hands the model; emits nothing on its own."""

    def __init__(self):
        super().__init__("fake")
        self.audio: list[str] = []
        self.texts: list[str] = []

    async def connect(self, session, agent, callback):
        pass

    async def append_audio(self, base64_audio):
        self.audio.append(base64_audio)

    async def send_text(self, text):
        self.texts.append(text)

    async def disconnect(self):
        pass


class _Agent(Agent):
    def __init__(self, name="general", realtime_runner_cls=_Adapter):
        super().__init__(name, _Runner(), realtime_runner_cls=realtime_runner_cls)

    def get_description(self):
        return "fake"

    def get_a2a_card(self):
        return None

    def attach_tool(self, tool):
        pass

    def override_system_prompt(self, prompt):
        pass


class _Pre(PreHook):
    """A pre-hook that records what it sees. ``on_run`` and ``on_stream_input`` results are overridable."""

    def __init__(self, label="pre", on_run=None, on_input=None):
        self.label = label
        self._on_run = on_run
        self._on_input = on_input
        self.runs: list = []
        self.inputs: list = []
        self.contexts: list = []

    async def on_run(self, session, agent, requests):
        self.runs.append(requests)
        self.contexts.append((Session.current(), Agent.current()))
        if self._on_run is None:
            return requests
        result = self._on_run(requests)
        if isinstance(result, BaseException):
            raise result
        return result

    async def on_stream_input(self, session, agent, request):
        self.inputs.append(request)
        self.contexts.append((Session.current(), Agent.current()))
        if self._on_input is None:
            return request
        result = self._on_input(request)
        if isinstance(result, BaseException):
            raise result
        return result

    def name(self):
        return self.label


class _Post(PostHook):
    """A post-hook that records every event it sees (and the requests argument)."""

    def __init__(self, label="post", on_event=None):
        self.label = label
        self._on_event = on_event
        self.events: list = []
        self.requests: list = []
        self.contexts: list = []

    async def on_run(self, session, requests, agent, agent_reply):
        return agent_reply

    async def on_stream_event(self, session, requests, agent, event):
        self.events.append(event)
        self.requests.append(requests)
        self.contexts.append((Session.current(), Agent.current()))
        if self._on_event is None:
            return event
        result = self._on_event(session, event)
        if isinstance(result, BaseException):
            raise result
        return result

    def name(self):
        return self.label


def _connection(agent=None, loop=None):
    return RealtimeConnection("s1", agent or _Agent(), Runtime(InMemorySessionStore()), Session("s1"), loop or asyncio.get_running_loop())


def _transport():
    return QueueTransportFactory.create()


def _chunks(transport):
    consumer = transport.create_consumer(QueueName.OUTPUT)
    out = []
    while True:
        messages = consumer.fetch(10, 0.1)
        if not messages:
            return out
        for message in messages:
            out.append(StreamChunk.model_validate(json.loads(message.body)))
            consumer.ack(message)


def _kinds(chunks):
    return ["done" if c.done else ("error" if c.error else c.event.type) for c in chunks]


async def _feed(conn, events, settle=0.15):
    """Connect, feed adapter events, let the pacing loop run, then stop it."""
    await conn.connect()
    for kind, data in events:
        await conn.handle_framework_event(kind, data)
    await asyncio.sleep(settle)
    if conn._pacing_task:
        conn._pacing_task.cancel()


async def _settle(seconds=0.1):
    await asyncio.sleep(seconds)


TURN = [
    ("transcript_delta", {"delta": "Hello", "message_id": "m1"}),
    ("audio_delta", {"delta": "QUFB", "message_id": "m1"}),
    ("done", {"status": "completed"}),
]


class TestOutputHooks:
    @pytest.mark.asyncio
    async def test_a_post_hook_sees_every_event_in_order_and_the_turn_end(self):
        agent = _Agent()
        post = _Post()
        agent.post_hooks.append(post)
        conn = _connection(agent)
        await _feed(conn, [("input_transcript", {"text": "hi", "message_id": "u1"}), *TURN])

        assert [e.type for e in post.events] == ["agent_changed", "input_transcript", "text_delta", "audio_delta", "message_end"]
        assert _kinds(_chunks(_transport())) == ["agent_changed", "input_transcript", "text_delta", "audio_delta", "message_end", "done"]

    @pytest.mark.asyncio
    async def test_session_and_agent_are_current_inside_the_hook(self):
        agent = _Agent()
        post = _Post()
        agent.post_hooks.append(post)
        conn = _connection(agent)
        await _feed(conn, TURN)

        assert post.contexts and all(session is conn.session and current is agent for session, current in post.contexts)

    @pytest.mark.asyncio
    async def test_a_same_type_rewrite_is_what_the_edge_receives(self):
        agent = _Agent()
        agent.post_hooks.append(
            _Post(on_event=lambda s, e: TextDelta(message_id=e.message_id, content="[redacted]") if isinstance(e, TextDelta) else e)
        )
        conn = _connection(agent)
        await _feed(conn, TURN)

        [text] = [c for c in _chunks(_transport()) if c.event and c.event.type == "text_delta"]
        assert text.event.content == "[redacted]" and text.delta == "[redacted]"

    @pytest.mark.asyncio
    async def test_a_list_replaces_one_event_with_several(self):
        agent = _Agent()
        agent.post_hooks.append(
            _Post(
                on_event=lambda s, e: (
                    [TextDelta(message_id="m1", content="a"), TextDelta(message_id="m1", content="b")] if isinstance(e, TextDelta) else e
                )
            )
        )
        conn = _connection(agent)
        await _feed(conn, TURN)

        assert [c.delta for c in _chunks(_transport()) if c.delta] == ["a", "b"]

    @pytest.mark.asyncio
    async def test_dropped_audio_is_not_emitted_and_not_paced(self):
        agent = _Agent()
        agent.post_hooks.append(_Post(on_event=lambda s, e: None if isinstance(e, AudioDelta) else e))
        conn = _connection(agent)
        started = time.monotonic()
        await _feed(conn, [("audio_delta", {"delta": PCM_2S, "message_id": "m1"}), ("done", {"status": "completed"})], settle=0.3)

        assert "audio_delta" not in _kinds(_chunks(_transport()))
        assert time.monotonic() - started < 1.0  # two seconds of dropped audio would have paced for about 1.9 s

    @pytest.mark.asyncio
    async def test_pacing_follows_the_audio_a_hook_emits(self):
        agent = _Agent()
        longer = AudioDelta(message_id="m1", content=PCM_2S)
        agent.post_hooks.append(_Post(on_event=lambda s, e: longer if isinstance(e, AudioDelta) else e))
        conn = _connection(agent)
        await conn.connect()
        started = time.monotonic()
        await conn.handle_framework_event("audio_delta", {"delta": "QUFB", "message_id": "m1"})
        await conn.handle_framework_event("done", {"status": "completed"})
        done = False
        collected = []
        while not done and time.monotonic() - started < 4.0:
            await asyncio.sleep(0.05)
            collected += _chunks(_transport())
            done = any(c.done for c in collected)
        conn._pacing_task.cancel()

        assert done
        assert time.monotonic() - started > 1.5  # the 2 s the hook emitted, less the playback lead, though the model's audio was 3 bytes

    @pytest.mark.asyncio
    async def test_audio_a_hook_releases_at_the_turn_end_is_paced_not_sent_in_a_burst(self):
        """Hold-and-release is the documented pattern: released audio must still leave at playback speed, or a barge-in cannot drop it."""

        class HoldAudio(PostHook):
            async def on_run(self, session, requests, agent, agent_reply):
                return agent_reply

            async def on_stream_event(self, session, requests, agent, event):
                cache = session.get_volatile_cache()
                if isinstance(event, AudioDelta):
                    cache.set("held", [*(cache.get("held") or []), event])
                    return None
                if isinstance(event, MessageEnd):
                    held = cache.get("held") or []
                    cache.set("held", [])
                    return [*held, event]
                return event

            def name(self):
                return "hold-audio"

        half_second = base64.b64encode(b"\x00\x00" * 12000).decode()  # 0.5 s at 24 kHz
        agent = _Agent()
        agent.post_hooks.append(HoldAudio())
        conn = _connection(agent)
        await conn.connect()
        started = time.monotonic()
        for _ in range(3):
            await conn.handle_framework_event("audio_delta", {"delta": half_second, "message_id": "m1"})
        await conn.handle_framework_event("done", {"status": "completed"})

        await asyncio.sleep(0.3)
        early = _chunks(_transport())
        assert _kinds(early).count("audio_delta") < 3, "1.5 s of released audio was emitted in a burst"
        assert "done" not in _kinds(early)

        collected = list(early)
        while not any(c.done for c in collected) and time.monotonic() - started < 4.0:
            await asyncio.sleep(0.05)
            collected += _chunks(_transport())
        conn._pacing_task.cancel()

        assert _kinds(collected).count("audio_delta") == 3 and any(c.done for c in collected)
        assert time.monotonic() - started > 1.2  # 1.5 s of audio less the playback lead

    @pytest.mark.asyncio
    async def test_the_turn_end_carries_the_last_output_events_message_id(self):
        agent = _Agent()
        conn = _connection(agent)
        await _feed(
            conn,
            [
                ("transcript_delta", {"delta": "x", "message_id": "m1"}),
                ("audio_delta", {"delta": "QUFB", "message_id": "m2"}),
                ("done", {"status": "completed"}),
            ],
        )
        [end] = [c.event for c in _chunks(_transport()) if c.event and c.event.type == "message_end"]
        assert end.message_id == "m2"

    @pytest.mark.asyncio
    async def test_a_turn_with_no_output_ends_with_a_fresh_message_id(self):
        conn = _connection()
        await _feed(conn, [("done", {"status": "completed"}), ("done", {"status": "completed"})])
        ends = [c.event.message_id for c in _chunks(_transport()) if c.event and c.event.type == "message_end"]
        assert len(ends) == 2 and all(len(i) == 32 for i in ends) and ends[0] != ends[1]

    @pytest.mark.asyncio
    async def test_a_hook_can_hold_text_and_release_it_at_the_turn_end(self):
        class Holding(PostHook):
            async def on_run(self, session, requests, agent, agent_reply):
                return agent_reply

            async def on_stream_event(self, session, requests, agent, event):
                cache = session.get_volatile_cache()
                if isinstance(event, TextDelta):
                    cache.set("held", (cache.get("held") or "") + event.content)
                    return None
                if isinstance(event, MessageEnd):
                    held = cache.get("held") or ""
                    cache.set("held", "")
                    return [TextDelta(message_id=event.message_id, content=held.upper()), event]
                return event

            def name(self):
                return "holding"

        agent = _Agent()
        agent.post_hooks.append(Holding())
        conn = _connection(agent)
        await _feed(
            conn,
            [
                ("transcript_delta", {"delta": "hel", "message_id": "m1"}),
                ("transcript_delta", {"delta": "lo", "message_id": "m1"}),
                ("done", {"status": "completed"}),
            ],
        )
        chunks = _chunks(_transport())
        assert _kinds(chunks) == ["agent_changed", "text_delta", "message_end", "done"]
        assert chunks[1].delta == "HELLO"

    @pytest.mark.asyncio
    async def test_a_barge_in_reaches_the_hooks_in_order(self):
        agent = _Agent()
        post = _Post()
        agent.post_hooks.append(post)
        conn = _connection(agent)
        await _feed(
            conn,
            [("interrupt", {}), ("transcript_delta", {"delta": "next", "message_id": "m2"}), ("done", {"status": "completed"})],
        )
        # The pool queues an interrupt ahead of the control events it kept (here the starting speaker); hooks see that order.
        assert [e.type for e in post.events] == ["interrupt", "agent_changed", "text_delta", "message_end"]
        assert isinstance(post.events[0], Interrupt) and isinstance(post.events[1], AgentChanged)

    @pytest.mark.asyncio
    async def test_the_requests_argument_is_the_last_text_turn_sent_to_the_model(self):
        agent = _Agent()
        post = _Post()
        agent.post_hooks.append(post)
        conn = _connection(agent)
        await conn.connect()
        conn.send_text(AgentRequestText(prompt="what is my balance"))
        await _settle()
        await conn.handle_framework_event("transcript_delta", {"delta": "ok", "message_id": "m1"})
        await _settle()
        conn._pacing_task.cancel()

        assert post.requests[0] == []  # the first event (the starting speaker) precedes any text turn
        assert [r.prompt for r in post.requests[-1]] == ["what is my balance"]

    @pytest.mark.asyncio
    async def test_stream_halt_sends_one_error_chunk_and_closes_the_call(self):
        agent = _Agent()
        agent.post_hooks.append(_Post(on_event=lambda s, e: StreamHalt("not allowed") if isinstance(e, TextDelta) else e))
        conn = _connection(agent)
        await _feed(conn, TURN)
        await _settle()

        errors = [c for c in _chunks(_transport()) if c.error]
        assert [(c.error, c.done) for c in errors] == [("not allowed", True)]
        assert conn.closed and conn.failure_reported

    @pytest.mark.asyncio
    async def test_any_other_hook_exception_ends_the_call_with_a_generic_message(self, caplog):
        agent = _Agent()
        agent.post_hooks.append(_Post(on_event=lambda s, e: RuntimeError("secret detail") if isinstance(e, TextDelta) else e))
        conn = _connection(agent)
        with caplog.at_level(logging.ERROR):
            await _feed(conn, TURN)
            await _settle()

        [error] = [c for c in _chunks(_transport()) if c.error]
        assert error.error == "Realtime output hook failed" and "secret detail" not in error.error
        assert "secret detail" in caplog.text  # logged with the traceback
        assert conn.closed

    @pytest.mark.asyncio
    async def test_a_hook_returning_another_event_type_ends_the_call(self):
        agent = _Agent()
        agent.post_hooks.append(_Post(on_event=lambda s, e: Interrupt() if isinstance(e, TextDelta) else e))
        conn = _connection(agent)
        await _feed(conn, TURN)
        await _settle()

        assert [c.error for c in _chunks(_transport()) if c.error] == ["Realtime output hook failed"]

    @pytest.mark.asyncio
    async def test_system_post_hooks_run_before_agent_hooks(self, monkeypatch):
        order = []
        system = _Post("system", on_event=lambda s, e: order.append("system") or e)
        agent_hook = _Post("agent", on_event=lambda s, e: order.append("agent") or e)
        monkeypatch.setattr(Runtime, "_system_post_hooks", [system])
        agent = _Agent()
        agent.post_hooks.append(agent_hook)
        conn = _connection(agent)
        await _feed(conn, [("done", {"status": "completed"})])

        assert order[:2] == ["system", "agent"]


class TestInputHooks:
    @pytest.mark.asyncio
    async def test_with_no_hooks_audio_and_text_reach_the_model_as_before(self):
        conn = _connection()
        conn.adapter.input_sample_rate = 16000
        conn.append_audio(AgentRequestVoice(audio_data=base64.b64encode(b"\x00\x00" * 2400).decode(), name="clip"))
        conn.send_text(AgentRequestText(prompt="hi"))
        await _settle()

        [converted] = conn.adapter.audio
        assert len(base64.b64decode(converted)) == 3200  # 100 ms at 16 kHz
        assert conn.adapter.texts == ["hi"]

    @pytest.mark.asyncio
    async def test_a_pre_hook_sees_the_audio_chunk_with_its_name_and_context(self):
        agent = _Agent()
        pre = _Pre()
        agent.pre_hooks.append(pre)
        conn = _connection(agent)
        conn.append_audio(AgentRequestVoice(audio_data="QUFB", name="clip", mime_type="audio/pcm"))
        await _settle()

        [seen] = pre.inputs
        assert (seen.name, seen.mime_type) == ("clip", "audio/pcm")
        assert all(session is conn.session and current is agent for session, current in pre.contexts)
        assert len(conn.adapter.audio) == 1

    @pytest.mark.asyncio
    async def test_none_drops_the_chunk_before_the_model(self):
        agent = _Agent()
        agent.pre_hooks.append(_Pre(on_input=lambda r: None))
        conn = _connection(agent)
        conn.append_audio(AgentRequestVoice(audio_data="QUFB", name="clip"))
        await _settle()

        assert conn.adapter.audio == []

    @pytest.mark.asyncio
    async def test_a_list_of_voice_sends_each_chunk_at_the_models_rate(self):
        agent = _Agent()
        chunk = AgentRequestVoice(audio_data=base64.b64encode(b"\x00\x00" * 2400).decode(), name="clip")
        agent.pre_hooks.append(_Pre(on_input=lambda r: [chunk, chunk]))
        conn = _connection(agent)
        conn.adapter.input_sample_rate = 16000
        conn.append_audio(AgentRequestVoice(audio_data="QUFB", name="clip"))
        await _settle()

        assert len(conn.adapter.audio) == 2 and all(len(base64.b64decode(a)) == 3200 for a in conn.adapter.audio)

    @pytest.mark.asyncio
    async def test_text_a_hook_made_from_audio_goes_through_the_text_hooks_and_is_sent_once(self):
        agent = _Agent()
        emitter = _Pre("emitter", on_input=lambda r: [AgentRequestText(prompt="hello")])
        shout = _Pre("shout", on_run=lambda requests: [AgentRequestText(prompt=requests[0].prompt.upper())])
        agent.pre_hooks.extend([emitter, shout])
        conn = _connection(agent)
        conn.append_audio(AgentRequestVoice(audio_data="QUFB", name="clip"))
        await _settle()

        assert conn.adapter.texts == ["HELLO"]
        assert conn.adapter.audio == []
        assert shout.inputs == []  # the list ended the audio chain

    @pytest.mark.asyncio
    async def test_typed_text_runs_agent_hooks_then_system_hooks(self, monkeypatch):
        order = []
        monkeypatch.setattr(Runtime, "_system_pre_hooks", [_Pre("system", on_run=lambda r: order.append("system") or r)])
        agent = _Agent()
        agent.pre_hooks.append(_Pre("agent", on_run=lambda r: order.append("agent") or r))
        conn = _connection(agent)
        conn.send_text(AgentRequestText(prompt="hi"))
        await _settle()

        assert order == ["agent", "system"] and conn.adapter.texts == ["hi"]

    @pytest.mark.asyncio
    async def test_a_changed_turn_is_what_the_model_receives(self):
        agent = _Agent()
        agent.pre_hooks.append(_Pre(on_run=lambda r: [AgentRequestText(prompt=r[0].prompt + " (context added)")]))
        conn = _connection(agent)
        conn.send_text(AgentRequestText(prompt="hi"))
        await _settle()

        assert conn.adapter.texts == ["hi (context added)"]

    @pytest.mark.asyncio
    async def test_several_text_requests_are_one_send_and_other_types_are_dropped(self):
        from agentkernel.core.model import AgentRequestAny

        agent = _Agent()
        agent.pre_hooks.append(
            _Pre(on_run=lambda r: [AgentRequestText(prompt="a"), AgentRequestAny(name="ctx", content={"k": 1}), AgentRequestText(prompt="b")])
        )
        conn = _connection(agent)
        conn.send_text(AgentRequestText(prompt="x"))
        await _settle()

        assert conn.adapter.texts == ["a\nb"]

    @pytest.mark.asyncio
    async def test_nothing_is_sent_when_no_text_is_left(self):
        agent = _Agent()
        agent.pre_hooks.append(_Pre(on_run=lambda r: []))
        conn = _connection(agent)
        conn.send_text(AgentRequestText(prompt="x"))
        await _settle()

        assert conn.adapter.texts == []

    @pytest.mark.asyncio
    async def test_a_halting_pre_hook_sends_an_error_chunk_and_nothing_to_the_model(self):
        agent = _Agent()
        agent.pre_hooks.append(_Pre(on_run=lambda r: AgentReplyText(response="I can't help with that")))
        conn = _connection(agent)
        conn.send_text(AgentRequestText(prompt="bad"))
        await _settle()

        [chunk] = _chunks(_transport())
        assert (chunk.error, chunk.done) == ("I can't help with that", True)
        assert conn.adapter.texts == [] and not conn.closed

    @pytest.mark.asyncio
    async def test_a_raising_pre_hook_sends_a_generic_error_and_the_call_continues(self):
        agent = _Agent()
        agent.pre_hooks.append(_Pre(on_run=lambda r: RuntimeError("internal detail")))
        conn = _connection(agent)
        conn.send_text(AgentRequestText(prompt="x"))
        await _settle()

        [chunk] = _chunks(_transport())
        assert chunk.error == "Your message could not be processed." and chunk.done
        assert conn.adapter.texts == [] and not conn.closed

    @pytest.mark.asyncio
    async def test_a_raising_audio_hook_drops_the_chunk_and_logs_the_first_failure_only_at_error(self, caplog):
        agent = _Agent()
        agent.pre_hooks.append(_Pre(on_input=lambda r: RuntimeError("boom")))
        conn = _connection(agent)
        with caplog.at_level(logging.DEBUG, logger="ak.pipeline.realtime_pool"):
            for _ in range(3):
                conn.append_audio(AgentRequestVoice(audio_data="QUFB", name="clip"))
            await _settle()

        errors = [r for r in caplog.records if r.levelno == logging.ERROR and "input hook failed" in r.getMessage()]
        debugs = [r for r in caplog.records if r.levelno == logging.DEBUG and "input hook failed" in r.getMessage()]
        assert len(errors) == 1 and len(debugs) == 2
        assert conn.adapter.audio == [] and _chunks(_transport()) == []  # no error chunk per audio chunk

    @pytest.mark.asyncio
    async def test_a_hook_returning_the_wrong_type_drops_the_chunk(self):
        agent = _Agent()
        agent.pre_hooks.append(_Pre("wrong", on_input=lambda r: AgentRequestText(prompt="x")))
        conn = _connection(agent)
        conn.append_audio(AgentRequestVoice(audio_data="QUFB", name="clip"))
        await _settle()

        assert conn.adapter.audio == [] and conn.adapter.texts == []


class TestCallEnd:
    @pytest.mark.asyncio
    async def test_closing_clears_the_volatile_cache(self):
        conn = _connection()
        conn.session.get_volatile_cache().set("hook-state", "left over")
        await conn.close()

        assert conn.session.get_volatile_cache().get("hook-state") is None

    @pytest.mark.asyncio
    async def test_a_failing_disconnect_still_clears_the_volatile_cache(self):
        class FailingAdapter(_Adapter):
            async def disconnect(self):
                raise RuntimeError("network error closing the native session")

        conn = _connection(_Agent(realtime_runner_cls=FailingAdapter))
        conn.session.get_volatile_cache().set("hook-state", "left over")
        with pytest.raises(RuntimeError):
            await conn.close()

        # The in-memory store hands the next call this same Session, so leftover hook state would leak into it.
        assert conn.session.get_volatile_cache().get("hook-state") is None


class TestStartupWarning:
    @staticmethod
    def _pool_warnings(caplog):
        """Warnings the pool logged. Not every record: other loggers (Runtime.register logs at DEBUG) depend on test order."""
        return [r for r in caplog.records if r.name == "ak.pipeline.realtime_pool" and r.levelno >= logging.WARNING]

    @staticmethod
    def _config(monkeypatch, input_enabled):
        class _Cfg:
            guardrail = _GuardrailConfig(input=_GuardrailParamConfig(enabled=input_enabled))

        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))

    @staticmethod
    def _runtime(monkeypatch):
        runtime = Runtime(InMemorySessionStore())
        runtime.register(_Agent("voice"))
        runtime.register(_Agent("chat", realtime_runner_cls=None))
        monkeypatch.setattr(Runtime, "current", staticmethod(lambda: runtime))

    def test_warns_once_for_each_realtime_agent_when_the_input_guardrail_is_on(self, monkeypatch, caplog):
        self._config(monkeypatch, True)
        self._runtime(monkeypatch)
        with caplog.at_level(logging.WARNING, logger="ak.pipeline.realtime_pool"):
            RealtimeConnectionPool()._warn_unchecked_audio()

        [warning] = self._pool_warnings(caplog)
        assert "'voice'" in warning.getMessage() and "typed text only" in warning.getMessage()

    def test_stays_silent_when_the_input_guardrail_is_off(self, monkeypatch, caplog):
        self._config(monkeypatch, False)
        self._runtime(monkeypatch)
        with caplog.at_level(logging.WARNING, logger="ak.pipeline.realtime_pool"):
            RealtimeConnectionPool()._warn_unchecked_audio()

        assert self._pool_warnings(caplog) == []

    def test_initialize_warns_once_per_realtime_agent(self, monkeypatch, caplog):
        self._config(monkeypatch, True)
        self._runtime(monkeypatch)
        with caplog.at_level(logging.WARNING, logger="ak.pipeline.realtime_pool"):
            RealtimeConnectionPool.initialize()
            RealtimeConnectionPool.initialize()  # the second call returns the pool and must not warn again

        warnings = self._pool_warnings(caplog)
        assert len(warnings) == 1 and "'voice'" in warnings[0].getMessage()
