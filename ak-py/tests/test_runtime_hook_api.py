"""The public hook API of Runtime (#927): run_pre_hooks, run_stream_input_hooks, run_stream_event_hooks."""

import pytest

from agentkernel import Agent, Runner
from agentkernel.core.event import AudioDelta, MessageEnd, RunPaused, TextDelta
from agentkernel.core.hooks import PostHook, PreHook, StreamHalt
from agentkernel.core.model import AgentReplyText, AgentRequestText, AgentRequestVoice, StreamChunk
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore


class _Runner(Runner):
    def __init__(self):
        super().__init__("test-runner")

    async def run(self, agent, session, requests):
        return AgentReplyText(response="ok")

    async def stream(self, agent, session, requests):
        raise NotImplementedError()
        yield


class _Agent(Agent):
    def __init__(self, name="general"):
        super().__init__(name, _Runner())

    def get_description(self):
        return "fake"

    def get_a2a_card(self):
        return None

    def attach_tool(self, tool):
        pass

    def override_system_prompt(self, prompt):
        pass


class _InputHook(PreHook):
    """A pre-hook whose on_stream_input returns what it is given, and records the order of calls."""

    def __init__(self, label, result="pass", calls=None):
        self.label = label
        self.result = result
        self.calls = calls if calls is not None else []

    async def on_run(self, session, agent, requests):
        self.calls.append(("on_run", self.label))
        return requests

    async def on_stream_input(self, session, agent, request):
        self.calls.append(("on_stream_input", self.label))
        return request if self.result == "pass" else self.result

    def name(self):
        return self.label


class _EventHook(PostHook):
    def __init__(self, label, result="pass", calls=None):
        self.label = label
        self.result = result
        self.calls = calls if calls is not None else []

    async def on_run(self, session, requests, agent, agent_reply):
        return agent_reply

    async def on_stream_event(self, session, requests, agent, event):
        self.calls.append(self.label)
        return event if self.result == "pass" else self.result

    def name(self):
        return self.label


def _voice(data="QUFB"):
    return AgentRequestVoice(audio_data=data, name="clip")


@pytest.fixture
def runtime():
    return Runtime(InMemorySessionStore())


@pytest.fixture
def agent():
    return _Agent()


@pytest.fixture
def session(runtime):
    return runtime.sessions().new("s1")


class TestRunPreHooks:
    @pytest.mark.asyncio
    async def test_runs_agent_hooks_then_system_hooks_and_returns_the_requests(self, runtime, agent, session, monkeypatch):
        calls = []
        monkeypatch.setattr(Runtime, "_system_pre_hooks", [_InputHook("system", calls=calls)])
        agent.pre_hooks.append(_InputHook("agent", calls=calls))

        requests = [AgentRequestText(prompt="hi")]
        assert await runtime.run_pre_hooks(agent, session, requests) == requests
        assert [label for _, label in calls] == ["agent", "system"]

    @pytest.mark.asyncio
    async def test_a_halting_hook_returns_its_reply(self, runtime, agent, session, monkeypatch):
        class Halting(_InputHook):
            async def on_run(self, session, agent, requests):
                return AgentReplyText(response="blocked")

        monkeypatch.setattr(Runtime, "_system_pre_hooks", [])
        agent.pre_hooks.append(Halting("halt"))
        reply = await runtime.run_pre_hooks(agent, session, [AgentRequestText(prompt="hi")])
        assert isinstance(reply, AgentReplyText) and reply.response == "blocked"

    @pytest.mark.asyncio
    async def test_a_wrong_type_raises_naming_the_hook(self, runtime, agent, session, monkeypatch):
        class Bad(_InputHook):
            async def on_run(self, session, agent, requests):
                return "nope"

        monkeypatch.setattr(Runtime, "_system_pre_hooks", [])
        agent.pre_hooks.append(Bad("bad"))
        with pytest.raises(TypeError, match="PreHook 'bad'"):
            await runtime.run_pre_hooks(agent, session, [AgentRequestText(prompt="hi")])


class TestRunStreamInputHooks:
    @pytest.mark.asyncio
    async def test_the_default_passes_the_chunk_through(self, runtime, agent, session, monkeypatch):
        monkeypatch.setattr(Runtime, "_system_pre_hooks", [])

        class OnRunOnly(PreHook):
            async def on_run(self, session, agent, requests):
                return requests

            def name(self):
                return "on-run-only"

        agent.pre_hooks.append(OnRunOnly())
        chunk = _voice()
        assert await runtime.run_stream_input_hooks(agent, session, chunk) == ([chunk], [])

    @pytest.mark.asyncio
    async def test_agent_hooks_run_before_system_hooks(self, runtime, agent, session, monkeypatch):
        calls = []
        monkeypatch.setattr(Runtime, "_system_pre_hooks", [_InputHook("system", calls=calls)])
        agent.pre_hooks.append(_InputHook("agent", calls=calls))
        await runtime.run_stream_input_hooks(agent, session, _voice())
        assert calls == [("on_stream_input", "agent"), ("on_stream_input", "system")]

    @pytest.mark.asyncio
    async def test_a_modified_chunk_reaches_the_next_hook(self, runtime, agent, session, monkeypatch):
        monkeypatch.setattr(Runtime, "_system_pre_hooks", [])
        seen = []

        class Recording(_InputHook):
            async def on_stream_input(self, session, agent, request):
                seen.append(request.audio_data)
                return request

        agent.pre_hooks.extend([_InputHook("first", result=_voice("CHANGED")), Recording("second")])
        assert await runtime.run_stream_input_hooks(agent, session, _voice("ORIGINAL")) == ([_voice("CHANGED")], [])
        assert seen == ["CHANGED"]

    @pytest.mark.asyncio
    async def test_none_drops_the_chunk_and_later_hooks_do_not_run(self, runtime, agent, session, monkeypatch):
        calls = []
        monkeypatch.setattr(Runtime, "_system_pre_hooks", [_InputHook("system", calls=calls)])
        agent.pre_hooks.append(_InputHook("drop", result=None, calls=calls))
        assert await runtime.run_stream_input_hooks(agent, session, _voice()) == ([], [])
        assert calls == [("on_stream_input", "drop")]

    @pytest.mark.asyncio
    async def test_a_list_ends_the_chain_and_splits_voice_from_text(self, runtime, agent, session, monkeypatch):
        calls = []
        monkeypatch.setattr(Runtime, "_system_pre_hooks", [_InputHook("system", calls=calls)])
        a, b, words = _voice("A"), _voice("B"), AgentRequestText(prompt="hello")
        agent.pre_hooks.append(_InputHook("emit", result=[a, words, b], calls=calls))
        assert await runtime.run_stream_input_hooks(agent, session, _voice()) == ([a, b], [words])
        assert calls == [("on_stream_input", "emit")]

    @pytest.mark.asyncio
    async def test_a_single_request_of_another_type_raises_naming_the_hook(self, runtime, agent, session, monkeypatch):
        monkeypatch.setattr(Runtime, "_system_pre_hooks", [])
        agent.pre_hooks.append(_InputHook("wrong", result=AgentRequestText(prompt="x")))
        with pytest.raises(TypeError, match="PreHook 'wrong'.*Return a list"):
            await runtime.run_stream_input_hooks(agent, session, _voice())

    @pytest.mark.asyncio
    async def test_a_list_item_of_another_type_raises_naming_the_hook(self, runtime, agent, session, monkeypatch):
        monkeypatch.setattr(Runtime, "_system_pre_hooks", [])
        agent.pre_hooks.append(_InputHook("wrong", result=[_voice(), "text"]))
        with pytest.raises(TypeError, match="PreHook 'wrong'"):
            await runtime.run_stream_input_hooks(agent, session, _voice())


class TestRunStreamEventHooks:
    @staticmethod
    def _delta(text="hi"):
        return TextDelta(message_id="m1", content=text)

    @pytest.mark.asyncio
    async def test_with_no_hooks_the_event_is_emitted_as_is(self, runtime, agent, session, monkeypatch):
        monkeypatch.setattr(Runtime, "_system_post_hooks", [])
        event = self._delta()
        assert await runtime.run_stream_event_hooks(agent, session, [], event) == [event]

    @pytest.mark.asyncio
    async def test_system_hooks_run_before_agent_hooks(self, runtime, agent, session, monkeypatch):
        calls = []
        monkeypatch.setattr(Runtime, "_system_post_hooks", [_EventHook("system", calls=calls)])
        agent.post_hooks.append(_EventHook("agent", calls=calls))
        await runtime.run_stream_event_hooks(agent, session, [], self._delta())
        assert calls == ["system", "agent"]

    @pytest.mark.asyncio
    async def test_a_same_type_rewrite_reaches_the_next_hook(self, runtime, agent, session, monkeypatch):
        monkeypatch.setattr(Runtime, "_system_post_hooks", [])
        agent.post_hooks.append(_EventHook("rewrite", result=self._delta("rewritten")))
        assert await runtime.run_stream_event_hooks(agent, session, [], self._delta("original")) == [self._delta("rewritten")]

    @pytest.mark.asyncio
    async def test_none_drops_the_event(self, runtime, agent, session, monkeypatch):
        calls = []
        monkeypatch.setattr(Runtime, "_system_post_hooks", [])
        agent.post_hooks.extend([_EventHook("drop", result=None, calls=calls), _EventHook("later", calls=calls)])
        assert await runtime.run_stream_event_hooks(agent, session, [], self._delta()) == []
        assert calls == ["drop"]

    @pytest.mark.asyncio
    async def test_a_list_replaces_the_event_and_ends_the_chain(self, runtime, agent, session, monkeypatch):
        calls = []
        monkeypatch.setattr(Runtime, "_system_post_hooks", [])
        replacement = [self._delta("a"), MessageEnd(message_id="m1")]
        agent.post_hooks.extend([_EventHook("emit", result=replacement, calls=calls), _EventHook("later", calls=calls)])
        assert await runtime.run_stream_event_hooks(agent, session, [], self._delta()) == replacement
        assert calls == ["emit"]

    @pytest.mark.asyncio
    async def test_a_single_event_of_another_type_raises_naming_the_hook(self, runtime, agent, session, monkeypatch):
        monkeypatch.setattr(Runtime, "_system_post_hooks", [])
        agent.post_hooks.append(_EventHook("wrong", result=AudioDelta(message_id="m1", content="QUFB")))
        with pytest.raises(TypeError, match="PostHook 'wrong'.*Return a list"):
            await runtime.run_stream_event_hooks(agent, session, [], self._delta())

    @pytest.mark.asyncio
    async def test_stream_halt_propagates(self, runtime, agent, session, monkeypatch):
        class Halting(_EventHook):
            async def on_stream_event(self, session, requests, agent, event):
                raise StreamHalt("stop")

        monkeypatch.setattr(Runtime, "_system_post_hooks", [])
        agent.post_hooks.append(Halting("halt"))
        with pytest.raises(StreamHalt) as halted:
            await runtime.run_stream_event_hooks(agent, session, [], self._delta())
        assert halted.value.reason == "stop"

    @pytest.mark.asyncio
    async def test_the_requests_argument_reaches_the_hook(self, runtime, agent, session, monkeypatch):
        seen = []

        class Recording(_EventHook):
            async def on_stream_event(self, session, requests, agent, event):
                seen.append(requests)
                return event

        monkeypatch.setattr(Runtime, "_system_post_hooks", [])
        agent.post_hooks.append(Recording("rec"))
        turn = [AgentRequestText(prompt="question")]
        await runtime.run_stream_event_hooks(agent, session, turn, self._delta())
        assert seen == [turn]


class TestStreamStillWarnsWhenAHookDropsAPause:
    """Runtime.stream shares the extracted loop; the pause warning must still name the hook that dropped it."""

    @pytest.mark.asyncio
    async def test_the_warning_names_the_dropping_hook(self, runtime, session, monkeypatch, caplog):
        class PausingRunner(_Runner):
            async def stream(self, agent, session, requests):
                yield RunPaused(run_id="r1", agent="general", interruptions=[])

        agent = _Agent()
        agent._runner = PausingRunner()
        monkeypatch.setattr(Runtime, "_system_pre_hooks", [])
        monkeypatch.setattr(Runtime, "_system_post_hooks", [])
        agent.post_hooks.append(_EventHook("swallow", result=None))
        runtime.register(agent)

        with caplog.at_level("WARNING"):
            chunks = [c async for c in runtime.stream(agent, session, [AgentRequestText(prompt="hi")])]
        assert chunks[-1] == StreamChunk(done=True)
        assert any("swallow" in record.getMessage() for record in caplog.records)
