"""Tests for the A2UI labelling capability.

The hook's whole rule is "did the reply parse?", with the config block standing in for everything
it deliberately does not inspect — no message names, no `version`, no component types. These tests
pin both halves: what gets labelled, and what is left alone so the config block cannot collide with
an `output_type` agent.
"""

import pytest

from agentkernel.a2ui.hook import A2UIPostHook, A2UIPostHookFactory, NoOpA2UIPostHook
from agentkernel.core.config import AKConfig
from agentkernel.core.model import AgentReplyAny, AgentReplyImage, AgentReplyText

AGENT_NAME = "expenses"


class _Agent:
    """Minimal stand-in: the hook reads nothing but the name."""

    def __init__(self, name: str = AGENT_NAME):
        self.name = name


def _configure(monkeypatch, enabled: bool = True, agents=None, mode: str = "rest_sync"):
    class _A2UI:
        pass

    class _Execution:
        pass

    class _Cfg:
        pass

    _A2UI.enabled = enabled
    _A2UI.agents = agents
    _Execution.mode = mode
    _Cfg.a2ui = _A2UI
    _Cfg.execution = _Execution
    monkeypatch.setattr(AKConfig, "get", classmethod(lambda cls: _Cfg))


async def _run(hook, reply, agent=None):
    return await hook.on_run(None, [], agent or _Agent(), reply)


class TestLabelling:
    """A reply whose body parses is labelled; the declaration is what makes that safe."""

    @pytest.mark.asyncio
    async def test_json_object_is_labelled(self, monkeypatch):
        _configure(monkeypatch)
        content = {"version": "v1.0", "createSurface": {"surfaceId": "s1"}}

        result = await _run(A2UIPostHook(), AgentReplyText(response='{"version": "v1.0", "createSurface": {"surfaceId": "s1"}}'))

        assert isinstance(result, AgentReplyAny)
        assert result.content == content
        assert result.media_type == "application/a2ui+json"

    @pytest.mark.asyncio
    async def test_json_array_is_labelled(self, monkeypatch):
        """On v0.9.1 a UI is a sequence of messages, so a reply may carry an array."""
        _configure(monkeypatch)

        result = await _run(A2UIPostHook(), AgentReplyText(response='[{"createSurface": {}}, {"updateComponents": {}}]'))

        assert isinstance(result, AgentReplyAny)
        assert result.content == [{"createSurface": {}}, {"updateComponents": {}}]

    @pytest.mark.asyncio
    async def test_the_prompt_is_carried_over(self, monkeypatch):
        _configure(monkeypatch)

        result = await _run(A2UIPostHook(), AgentReplyText(response='{"a": 1}', prompt="file an expense"))

        assert result.prompt == "file an expense"


class TestLeftAlone:
    """Everything the hook declines to touch, and why each one matters."""

    @pytest.mark.asyncio
    async def test_prose_does_not_parse_so_is_never_labelled(self, monkeypatch):
        """This is what keeps a greeting a plain string — most turns look like this."""
        _configure(monkeypatch)
        reply = AgentReplyText(response="Hello! How can I help?")

        assert await _run(A2UIPostHook(), reply) is reply

    @pytest.mark.asyncio
    async def test_a_structured_reply_is_skipped_not_labelled(self, monkeypatch):
        """The guard that stops the config block colliding with an output_type agent: its schema is
        the application's, so labelling every structured reply would stamp prose as A2UI."""
        _configure(monkeypatch)
        reply = AgentReplyAny(content={"kind": "text", "text": "Hello!"})

        assert await _run(A2UIPostHook(), reply) is reply

    @pytest.mark.asyncio
    async def test_an_image_reply_is_skipped(self, monkeypatch):
        _configure(monkeypatch)
        reply = AgentReplyImage(response="here", image_data="x", name="i.png", mime_type="image/png")

        assert await _run(A2UIPostHook(), reply) is reply

    @pytest.mark.asyncio
    async def test_a_body_parsing_to_a_scalar_is_skipped(self, monkeypatch):
        """json.loads("4") succeeds and yields an int, which is not a payload."""
        _configure(monkeypatch)
        reply = AgentReplyText(response="4")

        assert await _run(A2UIPostHook(), reply) is reply

    @pytest.mark.asyncio
    async def test_an_empty_reply_is_skipped(self, monkeypatch):
        _configure(monkeypatch)
        reply = AgentReplyText(response="")

        assert await _run(A2UIPostHook(), reply) is reply


class TestAgentScoping:
    """`agents` is the declaration the detection rule leans on, so its edges matter."""

    @pytest.mark.asyncio
    async def test_an_unnamed_agent_is_excluded(self, monkeypatch):
        _configure(monkeypatch, agents=["other"])
        reply = AgentReplyText(response='{"a": 1}')

        assert await _run(A2UIPostHook(), reply) is reply

    @pytest.mark.asyncio
    async def test_a_named_agent_is_included(self, monkeypatch):
        _configure(monkeypatch, agents=[AGENT_NAME])

        result = await _run(A2UIPostHook(), AgentReplyText(response='{"a": 1}'))

        assert isinstance(result, AgentReplyAny)

    @pytest.mark.asyncio
    async def test_omitting_agents_covers_every_agent(self, monkeypatch):
        _configure(monkeypatch, agents=None)

        result = await _run(A2UIPostHook(), AgentReplyText(response='{"a": 1}'), agent=_Agent("anything"))

        assert isinstance(result, AgentReplyAny)


class TestFactory:
    """The hook chain must never break the runtime, so every failure resolves to the no-op."""

    def test_enabled_returns_the_real_hook(self, monkeypatch):
        _configure(monkeypatch, enabled=True)

        assert isinstance(A2UIPostHookFactory.get(), A2UIPostHook)

    def test_disabled_returns_the_no_op(self, monkeypatch):
        _configure(monkeypatch, enabled=False)

        assert isinstance(A2UIPostHookFactory.get(), NoOpA2UIPostHook)

    def test_an_absent_block_returns_the_no_op(self, monkeypatch):
        class _Cfg:
            pass

        monkeypatch.setattr(AKConfig, "get", classmethod(lambda cls: _Cfg))

        assert isinstance(A2UIPostHookFactory.get(), NoOpA2UIPostHook)

    def test_a_failing_config_read_returns_the_no_op(self, monkeypatch):
        def _boom(cls):
            raise RuntimeError("config unavailable")

        monkeypatch.setattr(AKConfig, "get", classmethod(_boom))

        assert isinstance(A2UIPostHookFactory.get(), NoOpA2UIPostHook)

    def test_streaming_mode_warns_that_the_hook_will_not_fire(self, monkeypatch, caplog):
        """`on_run` is never called for a streamed run, so the block would silently do nothing."""
        _configure(monkeypatch, enabled=True, mode="stream")

        with caplog.at_level("WARNING", logger="ak.a2ui.hook"):
            hook = A2UIPostHookFactory.get()

        assert isinstance(hook, A2UIPostHook)
        assert "never called for a streamed run" in caplog.text

    @pytest.mark.asyncio
    async def test_the_no_op_returns_the_reply_untouched(self):
        reply = AgentReplyText(response='{"a": 1}')

        assert await _run(NoOpA2UIPostHook(), reply) is reply


class TestEndToEnd:
    """Config on, an agent returning an A2UI document, and no application post-hook anywhere."""

    @pytest.mark.asyncio
    async def test_a_labelled_reply_reaches_the_response_builder_as_an_object(self, monkeypatch):
        from agentkernel.core.chat_service import ResponseBuilder

        _configure(monkeypatch)
        content = {"version": "v1.0", "createSurface": {"surfaceId": "expense_form"}}

        labelled = await _run(
            A2UIPostHookFactory.get(), AgentReplyText(response='{"version": "v1.0", "createSurface": {"surfaceId": "expense_form"}}')
        )
        response = ResponseBuilder.build_response(200, "s1", rest_api_mode=True, result=labelled)

        assert response["result"] == content
        assert response["media_type"] == "application/a2ui+json"
