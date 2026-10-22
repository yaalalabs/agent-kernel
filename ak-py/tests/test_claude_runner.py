"""
Tests for the Claude Agent SDK adapter (framework/claude).

`ClaudeSDKClient` is replaced by `FakeClient`, which records the options a run built and replays a script of
real SDK message objects. A script step may also be a coroutine function, run with the client in the middle of
the stream, whose return value (if any) is yielded: that is how the tests mirror transcript entries into the run's
SessionStore (as the SDK does before yielding a ResultMessage), stamp the result with the session id the run chose,
and call tool handlers (as the CLI does through the in-process MCP server).
"""

import asyncio
import base64
import logging
import os
from unittest.mock import AsyncMock

import pytest
from claude_agent_sdk import (
    AgentDefinition,
    AssistantMessage,
    ClaudeAgentOptions,
    DeferredToolUse,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ToolResultBlock,
    UserMessage,
)

import agentkernel.framework.claude.claude as claude_mod
from agentkernel.core import Session
from agentkernel.core.builder import SessionStoreBuilder
from agentkernel.core.event import RunPaused
from agentkernel.core.model import (
    AgentPausedReplyAny,
    AgentReplyAny,
    AgentReplyText,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
    AgentResumeRequestAny,
    ResumeDecision,
)
from agentkernel.core.paused_run import PausedRunState
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.serde import BinarySerde
from agentkernel.core.tool import ToolContext
from agentkernel.framework.claude.claude import (
    FRAMEWORK,
    ClaudeAgent,
    ClaudeAgentSpec,
    ClaudeModule,
    ClaudeRunner,
    ClaudeSession,
    ClaudeTelemetry,
    ClaudeToolBuilder,
    _ClaudeSessionStore,
    _ClaudeStreamMapper,
)

AK_MCP_SERVER = ClaudeToolBuilder.MCP_SERVER


class FakeClient:
    """Stands in for ClaudeSDKClient: records what a run built, replays a scripted message list."""

    instances: list["FakeClient"] = []
    script: list = []

    def __init__(self, options: ClaudeAgentOptions):
        self.options = options
        self.prompts: list = []
        self.entered = False
        self.exited = False
        FakeClient.instances.append(self)

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, *exc):
        self.exited = True
        return False

    async def query(self, prompt):
        if isinstance(prompt, str):
            self.prompts.append(prompt)
        else:
            self.prompts.append([message async for message in prompt])

    @property
    def session_id(self) -> str:
        return self.options.resume or self.options.session_id

    async def receive_response(self):
        for step in self.script:
            message = await step(self) if callable(step) else step
            if message is not None:
                yield message


@pytest.fixture
def fake_client(monkeypatch):
    FakeClient.instances = []
    FakeClient.script = []
    monkeypatch.setattr(claude_mod, "ClaudeSDKClient", FakeClient)
    return FakeClient


@pytest.fixture
def runtime():
    with Runtime(SessionStoreBuilder.build()) as rt:
        yield rt


def _result(session_id="", result="done", is_error=False, subtype="success", structured_output=None, errors=None):
    return ResultMessage(
        subtype=subtype,
        duration_ms=1,
        duration_api_ms=1,
        is_error=is_error,
        num_turns=1,
        session_id=session_id,
        result=result,
        structured_output=structured_output,
        errors=errors,
    )


def _mirror(*entries):
    """A script step that mirrors entries into the run's store, as the SDK does before yielding the result."""

    async def step(client):
        await client.options.session_store.append({"project_key": "p", "session_id": client.session_id}, list(entries))

    return step


def _finish(*entries, **result):
    """A script step that mirrors entries, then yields a ResultMessage carrying the session id the run chose."""

    async def step(client):
        await client.options.session_store.append({"project_key": "p", "session_id": client.session_id}, list(entries))
        return _result(session_id=client.session_id, **result)

    return step


async def _turn(fake_client, agent, session, prompt="hi"):
    """Runs one turn that mirrors a user and an assistant entry and ends in a successful result."""
    fake_client.script = [_finish({"type": "user", "uuid": f"u-{prompt}"}, {"type": "assistant", "uuid": f"a-{prompt}"})]
    return await agent.runner.run(agent, session, [AgentRequestText(prompt=prompt)])


def _module(*specs):
    return ClaudeModule(list(specs))


def _spec(name="general", **options):
    return ClaudeAgentSpec(name=name, description="A helpful agent", options=ClaudeAgentOptions(**options))


def double(x: int) -> int:
    """
    Double a number.
    :param x: The number to double.
    """
    return 2 * x


def _echo(text: str) -> str:
    """Echo the text back."""
    return text


# --- run ------------------------------------------------------------------------------------------


class TestRun:
    @pytest.mark.asyncio
    async def test_reply_is_the_result_text(self, fake_client, runtime):
        agent = _module(_spec()).get_agent("general")
        fake_client.script = [_result(result="hello")]

        reply = await agent.runner.run(agent, Session("s"), [AgentRequestText(prompt="hi")])

        assert isinstance(reply, AgentReplyText)
        assert reply.response == "hello"
        assert reply.prompt == "hi"
        assert fake_client.instances[0].prompts == ["hi"]
        assert fake_client.instances[0].exited

    @pytest.mark.asyncio
    async def test_falls_back_to_assistant_text_when_the_result_has_none(self, fake_client, runtime):
        agent = _module(_spec()).get_agent("general")
        fake_client.script = [AssistantMessage(content=[TextBlock(text="partial")], model="m"), _result(result=None)]

        reply = await agent.runner.run(agent, Session("s"), [AgentRequestText(prompt="hi")])

        assert reply.response == "partial"

    @pytest.mark.asyncio
    async def test_structured_output_becomes_agent_reply_any(self, fake_client, runtime):
        agent = _module(_spec(output_format={"type": "json_schema", "schema": {"type": "object"}})).get_agent("general")
        fake_client.script = [_result(result="{}", structured_output={"city": "Colombo"})]

        reply = await agent.runner.run(agent, Session("s"), [AgentRequestText(prompt="hi")])

        assert isinstance(reply, AgentReplyAny)
        assert reply.content == {"city": "Colombo"}

    @pytest.mark.asyncio
    async def test_error_result_is_reported_and_the_transcript_still_committed(self, fake_client, runtime):
        agent = _module(_spec()).get_agent("general")
        session = Session("s")
        fake_client.script = [
            _finish({"type": "user", "uuid": "u1"}, is_error=True, subtype="error_max_turns", result=None, errors=["max turns reached"])
        ]

        reply = await agent.runner.run(agent, session, [AgentRequestText(prompt="hi")])

        assert "error_max_turns" in reply.response and "max turns reached" in reply.response
        assert session.get(FRAMEWORK).transcript("general")[""] == [{"type": "user", "uuid": "u1"}]

    def test_api_error_names_the_status_not_the_success_subtype(self):
        failed = _result(is_error=True, result="Overloaded")
        failed.api_error_status = 529

        message = str(ClaudeRunner._error(failed))

        assert message == "Claude Agent SDK run failed (API error 529): Overloaded"

    @pytest.mark.asyncio
    async def test_a_run_without_a_result_commits_nothing(self, fake_client, runtime):
        agent = _module(_spec()).get_agent("general")
        session = Session("s")
        fake_client.script = [_mirror({"type": "user", "uuid": "u1"})]

        reply = await agent.runner.run(agent, session, [AgentRequestText(prompt="hi")])

        assert "without a result" in reply.response
        assert not session.get(FRAMEWORK).transcript("general")

    @pytest.mark.asyncio
    async def test_an_exception_mid_run_leaves_the_stored_transcript_intact(self, fake_client, runtime):
        agent = _module(_spec()).get_agent("general")
        session = Session("s")
        await _turn(fake_client, agent, session, prompt="first")
        before = session.get(FRAMEWORK).transcript("general")[""][:]

        async def boom(client):
            raise RuntimeError("CLI died")

        fake_client.script = [_mirror({"type": "user", "uuid": "u-second"}), boom]
        reply = await agent.runner.run(agent, session, [AgentRequestText(prompt="second")])

        assert "CLI died" in reply.response
        assert session.get(FRAMEWORK).transcript("general")[""] == before

    @pytest.mark.asyncio
    async def test_no_content_returns_before_resolving_options(self, fake_client, runtime):
        agent = _module(_spec()).get_agent("general")
        agent.resolve_run_options = AsyncMock(return_value={})

        reply = await agent.runner.run(agent, Session("s"), [])
        events = [e async for e in agent.runner.stream(agent, Session("s"), [])]

        assert "No valid content" in reply.response
        assert events == []
        agent.resolve_run_options.assert_not_awaited()
        assert fake_client.instances == []


# --- conversation continuity -------------------------------------------------------------------------


class TestConversation:
    @pytest.mark.asyncio
    async def test_first_turn_assigns_a_session_id_and_later_turns_resume_it(self, fake_client, runtime):
        agent = _module(_spec()).get_agent("general")
        session = Session("s")

        await _turn(fake_client, agent, session, prompt="one")
        first = fake_client.instances[0].options
        await _turn(fake_client, agent, session, prompt="two")
        second = fake_client.instances[1].options

        assert first.resume is None and first.session_id
        assert second.resume == first.session_id and second.session_id is None
        claude_session = session.get(FRAMEWORK)
        assert claude_session.session_id("general") == first.session_id
        assert [e["uuid"] for e in claude_session.transcript("general")[""]] == ["u-one", "a-one", "u-two", "a-two"]

    @pytest.mark.asyncio
    async def test_the_session_survives_the_session_store_serde(self, fake_client, runtime):
        agent = _module(_spec()).get_agent("general")
        session = Session("s")
        await _turn(fake_client, agent, session, prompt="one")

        serde = BinarySerde()
        restored = serde.loads(serde.dumps(session.get(FRAMEWORK)))

        assert restored.session_id("general") == session.get(FRAMEWORK).session_id("general")
        assert restored.transcript("general") == session.get(FRAMEWORK).transcript("general")

    @pytest.mark.asyncio
    async def test_each_agent_keeps_its_own_conversation(self, fake_client, runtime):
        module = _module(_spec("a"), _spec("b"))
        session = Session("s")

        await _turn(fake_client, module.get_agent("a"), session, prompt="for-a")
        await _turn(fake_client, module.get_agent("b"), session, prompt="for-b")

        data = session.get(FRAMEWORK)
        assert data.session_id("a") != data.session_id("b")
        assert fake_client.instances[1].options.resume is None  # b starts fresh, not on a's transcript


# --- session store --------------------------------------------------------------------------------------


class TestSessionStore:
    @staticmethod
    def _saved(session_id, transcript):
        claude_session = ClaudeSession()
        claude_session.save("a", session_id, transcript)
        return claude_session

    @pytest.mark.asyncio
    async def test_load_returns_none_for_an_unknown_transcript(self):
        store = _ClaudeSessionStore(ClaudeSession(), "a")
        assert await store.load({"project_key": "p", "session_id": "x"}) is None

    @pytest.mark.asyncio
    async def test_appends_are_buffered_until_commit_and_deduplicated_by_uuid(self):
        claude_session = ClaudeSession()
        store = _ClaudeSessionStore(claude_session, "a")
        key = {"project_key": "p", "session_id": "sid"}

        await store.append(key, [{"type": "user", "uuid": "u1"}, {"type": "title"}])
        await store.append(key, [{"type": "user", "uuid": "u1"}, {"type": "assistant", "uuid": "a1"}])

        assert claude_session.transcript("a") == {}
        assert await store.load(key) == [{"type": "user", "uuid": "u1"}, {"type": "title"}, {"type": "assistant", "uuid": "a1"}]
        store.commit("sid")
        assert claude_session.session_id("a") == "sid"
        assert len(claude_session.transcript("a")[""]) == 3

    @pytest.mark.asyncio
    async def test_project_key_is_ignored(self):
        store = _ClaudeSessionStore(self._saved("sid", {"": [{"type": "user", "uuid": "u1"}]}), "a")

        assert await store.load({"project_key": "another-cwd", "session_id": "sid"}) == [{"type": "user", "uuid": "u1"}]

    @pytest.mark.asyncio
    async def test_subagent_transcripts_are_listed_and_restored(self):
        store = _ClaudeSessionStore(self._saved("sid", {"": [{"type": "user"}], "subagents/agent-1": [{"type": "user"}]}), "a")
        await store.append({"project_key": "p", "session_id": "sid", "subpath": "subagents/agent-2"}, [{"type": "user"}])

        assert await store.list_subkeys({"project_key": "p", "session_id": "sid"}) == ["subagents/agent-1", "subagents/agent-2"]
        assert await store.list_subkeys({"project_key": "p", "session_id": "other"}) == []

    @pytest.mark.asyncio
    async def test_commit_keeps_only_the_session_the_turn_ended_on(self):
        claude_session = self._saved("old", {"": [{"type": "user", "uuid": "o1"}]})
        store = _ClaudeSessionStore(claude_session, "a")
        await store.append({"project_key": "p", "session_id": "new"}, [{"type": "user", "uuid": "n1"}])

        store.commit("new")

        assert claude_session.session_id("a") == "new"
        assert claude_session.transcript("a") == {"": [{"type": "user", "uuid": "n1"}]}

    def test_other_agents_conversations_are_untouched(self):
        claude_session = self._saved("sid-a", {"": [{"type": "user"}]})
        store = _ClaudeSessionStore(claude_session, "b")

        store.commit("sid-b")

        assert claude_session.session_id("a") == "sid-a"
        assert claude_session.session_id("b") == "sid-b"


# --- native options ----------------------------------------------------------------------------------


class TestNativeOptions:
    @pytest.mark.asyncio
    async def test_tools_are_served_by_the_ak_server_and_auto_approved(self, fake_client, runtime):
        spec = _spec(allowed_tools=["Read"])
        spec.tools = ClaudeToolBuilder.bind([double])
        agent = _module(spec).get_agent("general")
        fake_client.script = [_result()]

        await agent.runner.run(agent, Session("s"), [AgentRequestText(prompt="hi")])

        options = fake_client.instances[0].options
        assert AK_MCP_SERVER in options.mcp_servers
        assert options.allowed_tools == ["Read", "mcp__ak__double"]
        assert agent.agent.options.allowed_tools == ["Read"]  # the declaration is never mutated
        assert agent.agent.options.mcp_servers == {}

    @pytest.mark.asyncio
    async def test_no_tools_means_no_ak_server(self, fake_client, runtime):
        agent = _module(_spec()).get_agent("general")
        fake_client.script = [_result()]

        await agent.runner.run(agent, Session("s"), [AgentRequestText(prompt="hi")])

        options = fake_client.instances[0].options
        assert AK_MCP_SERVER not in options.mcp_servers
        assert options.session_store is not None
        assert options.include_partial_messages is False

    @pytest.mark.asyncio
    async def test_tool_handlers_see_the_tool_context_of_the_run(self, fake_client, runtime):
        seen = {}

        def whoami() -> str:
            """Report the agent the tool runs for."""
            seen["agent"] = ToolContext.get().agent.name
            seen["session"] = ToolContext.get().session.id
            return "ok"

        spec = _spec()
        spec.tools = ClaudeToolBuilder.bind([whoami])
        agent = _module(spec).get_agent("general")

        async def call_tool(client):
            tool = next(t for t in agent.agent.tools if t.name == "whoami")
            seen["result"] = await tool.handler({})

        fake_client.script = [call_tool, _result()]
        await agent.runner.run(agent, Session("tool-session"), [AgentRequestText(prompt="hi")])

        assert seen["agent"] == "general"
        assert seen["session"] == "tool-session"
        assert seen["result"] == {"content": [{"type": "text", "text": "ok"}]}


# --- run options ---------------------------------------------------------------------------------------


class TestRunOptions:
    def test_reserved_keys(self):
        assert set(ClaudeAgent.RESERVED_RUN_OPTIONS) == {
            "resume",
            "session_id",
            "continue_conversation",
            "fork_session",
            "resume_session_at",
            "resume_drops_turn",
            "session_store",
            "session_store_flush",
            "enable_file_checkpointing",
            "include_partial_messages",
        }

    @pytest.mark.asyncio
    async def test_declared_options_reach_the_client_and_the_declared_dict_is_untouched(self, fake_client, runtime):
        module = _module(_spec())
        spec = module.get_agent("general").agent
        module.run_options(spec, max_turns=3, model="sonnet")
        agent = module.get_agent("general")
        fake_client.script = [_result(), _result()]

        await agent.runner.run(agent, Session("s"), [AgentRequestText(prompt="hi")])
        await agent.runner.run(agent, Session("t"), [AgentRequestText(prompt="hi")])

        for client in fake_client.instances:
            assert client.options.max_turns == 3
            assert client.options.model == "sonnet"
        assert agent.run_options == {"max_turns": 3, "model": "sonnet"}
        assert agent.agent.options.max_turns is None

    @pytest.mark.asyncio
    async def test_a_factory_merged_value_wins_and_resolution_happens_once_per_run_and_stream(self, fake_client, runtime):
        agent = _module(_spec(max_turns=1)).get_agent("general")
        agent.run_options.update({"max_turns": 2})
        agent.resolve_run_options = AsyncMock(return_value={"max_turns": 9})
        session = Session("s")
        requests = [AgentRequestText(prompt="hi")]
        fake_client.script = [_result()]

        await agent.runner.run(agent, session, requests)
        _ = [e async for e in agent.runner.stream(agent, session, requests)]

        assert agent.resolve_run_options.await_count == 2
        agent.resolve_run_options.assert_awaited_with(session, requests)
        assert [c.options.max_turns for c in fake_client.instances] == [9, 9]

    @pytest.mark.asyncio
    async def test_an_ak_owned_field_wins_over_a_bypassed_declaration(self, fake_client, runtime):
        agent = _module(_spec()).get_agent("general")
        bypassed = {"session_store": object(), "session_store_flush": "eager", "session_id": "declared"}
        agent.run_options.update(bypassed)  # mutating the live dict skips validation
        fake_client.script = [_result()]

        await agent.runner.run(agent, Session("s"), [AgentRequestText(prompt="hi")])

        options = fake_client.instances[0].options
        assert isinstance(options.session_store, _ClaudeSessionStore)
        assert options.session_store_flush == "batched"
        assert options.session_id != "declared"

    def test_declared_conversation_controls_cannot_override_session_state(self, runtime):
        spec = _spec(
            resume="unrelated",
            continue_conversation=True,
            fork_session=True,
            resume_session_at="old-message",
            resume_drops_turn="old-turn",
            enable_file_checkpointing=True,
            include_partial_messages=True,
        )
        agent = _module(spec).get_agent("general")
        claude_session = ClaudeSession()

        first = agent.runner._native_options(agent, {}, claude_session, _ClaudeSessionStore(claude_session, agent.name), stream=False)
        assert first.session_id and first.resume is None
        assert first.continue_conversation is False
        assert first.fork_session is False
        assert first.resume_session_at is None
        assert first.resume_drops_turn is None
        assert first.enable_file_checkpointing is False
        assert first.include_partial_messages is False

        claude_session.save(agent.name, "saved", {"": [{"type": "user", "uuid": "u1"}]})
        later = agent.runner._native_options(agent, {}, claude_session, _ClaudeSessionStore(claude_session, agent.name), stream=True)
        assert later.resume == "saved" and later.session_id is None
        assert later.include_partial_messages is True

    def test_reserved_unknown_and_colliding_keys_are_rejected_at_declaration(self, runtime):
        spec = _spec()
        spec.tools = ClaudeToolBuilder.bind([double])
        module = _module(spec)

        for key in ClaudeAgent.RESERVED_RUN_OPTIONS:
            with pytest.raises(ValueError) as exc:
                module.run_options(spec, **{key: object()})
            assert f"'{key}'" in str(exc.value) and "'claude'" in str(exc.value)
        with pytest.raises(ValueError, match="not ClaudeAgentOptions fields"):
            module.run_options(spec, temperature=0.2)
        with pytest.raises(ValueError, match="reserved"):
            module.run_options(spec, mcp_servers={AK_MCP_SERVER: {}})
        with pytest.raises(ValueError, match="must be a dict"):
            module.run_options(spec, mcp_servers="/etc/mcp.json")

        module.run_options(spec, max_turns=2)
        assert module.get_agent("general").run_options == {"max_turns": 2}

    def test_declared_mcp_servers_are_checked_at_load(self, runtime):
        with pytest.raises(ValueError, match="reserved"):
            _module(_spec(mcp_servers={AK_MCP_SERVER: {}}))
        with_tools = _spec(mcp_servers="/etc/mcp.json")
        with_tools.tools = ClaudeToolBuilder.bind([double])
        with pytest.raises(ValueError, match="must be a dict"):
            _module(with_tools)

        _module(_spec("no-tools", mcp_servers="/etc/mcp.json"))  # a config-file path is fine without tools


# --- framework context -----------------------------------------------------------------------------


class TestFrameworkContext:
    """
    framework_context injection and write-back for ClaudeRunner. There is no native context slot a Claude Agent
    SDK tool handler can read, so the runner hands a copy through `ClaudeToolContext`, a per-run contextvar; a
    tool mutating the dict it returns round-trips back to the session on a successful call.
    """

    @pytest.mark.asyncio
    async def test_tool_sees_and_mutates_the_context(self, fake_client, runtime):
        def add_item(item: str) -> str:
            """Append an item to the caller's cart carried in framework_context."""
            claude_mod.ClaudeToolContext.get()["cart"].append(item)
            return "added"

        spec = _spec()
        spec.tools = ClaudeToolBuilder.bind([add_item])
        agent = _module(spec).get_agent("general")
        session = Session("s")
        session.set_framework_context({"cart": []})

        async def call_tool(client):
            tool = next(t for t in agent.agent.tools if t.name == "add_item")
            await tool.handler({"item": "apple"})

        fake_client.script = [call_tool, _result()]
        await agent.runner.run(agent, session, [AgentRequestText(prompt="hi")])

        assert session.get_framework_context() == {"cart": ["apple"]}

    @pytest.mark.asyncio
    async def test_absent_context_reads_back_as_none(self, fake_client, runtime):
        seen = {}

        def whoami() -> str:
            """Report whether a context dict is present."""
            seen["context"] = claude_mod.ClaudeToolContext.get()
            return "ok"

        spec = _spec()
        spec.tools = ClaudeToolBuilder.bind([whoami])
        agent = _module(spec).get_agent("general")
        session = Session("s")

        async def call_tool(client):
            tool = next(t for t in agent.agent.tools if t.name == "whoami")
            await tool.handler({})

        fake_client.script = [call_tool, _result()]
        await agent.runner.run(agent, session, [AgentRequestText(prompt="hi")])

        assert seen["context"] is None
        assert session.get_framework_context() is None

    @pytest.mark.asyncio
    async def test_get_outside_a_run_raises(self):
        with pytest.raises(RuntimeError, match="running Claude Agent SDK tool call"):
            claude_mod.ClaudeToolContext.get()

    @pytest.mark.asyncio
    async def test_error_leaves_stored_context_intact(self, fake_client, runtime):
        def boom() -> str:
            """Mutate the context then fail the turn."""
            claude_mod.ClaudeToolContext.get()["cart"].append("apple")
            raise RuntimeError("tool boom")

        spec = _spec()
        spec.tools = ClaudeToolBuilder.bind([boom])
        agent = _module(spec).get_agent("general")
        session = Session("s")
        session.set_framework_context({"cart": []})

        fake_client.script = [_result(is_error=True, subtype="error_max_turns")]
        reply = await agent.runner.run(agent, session, [AgentRequestText(prompt="hi")])

        assert isinstance(reply, AgentReplyText)
        assert session.get_framework_context() == {"cart": []}

    @pytest.mark.asyncio
    async def test_stream_normal_drain_writes_back(self, fake_client, runtime):
        def add_item(item: str) -> str:
            """Append an item to the caller's cart carried in framework_context."""
            claude_mod.ClaudeToolContext.get()["cart"].append(item)
            return "added"

        spec = _spec()
        spec.tools = ClaudeToolBuilder.bind([add_item])
        agent = _module(spec).get_agent("general")
        session = Session("stream-session")
        session.set_framework_context({"cart": []})

        async def call_tool(client):
            tool = next(t for t in agent.agent.tools if t.name == "add_item")
            await tool.handler({"item": "apple"})

        fake_client.script = [call_tool, _result()]
        events = [event async for event in agent.runner.stream(agent, session, [AgentRequestText(prompt="hi")])]

        assert events == []  # the fake script carries no raw stream events, only the result
        assert session.get_framework_context() == {"cart": ["apple"]}

    @pytest.mark.asyncio
    async def test_stream_disconnect_leaves_context_intact(self, fake_client, runtime):
        session = Session("stream-session")
        session.set_framework_context({"cart": []})
        agent = _module(_spec()).get_agent("general")

        async def hang(client):
            await asyncio.Event().wait()

        fake_client.script = [hang]
        agen = agent.runner.stream(agent, session, [AgentRequestText(prompt="hi")])
        task = asyncio.ensure_future(agen.__anext__())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await agen.aclose()

        assert session.get_framework_context() == {"cart": []}


# --- multimodal ----------------------------------------------------------------------------------------


class TestMultimodal:
    @pytest.mark.asyncio
    async def test_an_image_goes_as_one_streaming_input_message(self, fake_client, runtime):
        agent = _module(_spec()).get_agent("general")
        fake_client.script = [_result()]
        requests = [AgentRequestText(prompt="what is this?"), AgentRequestImage(image_data="aGk=", name="a.png", mime_type="image/png")]

        await agent.runner.run(agent, Session("s"), requests)

        [messages] = fake_client.instances[0].prompts
        assert messages == [
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "what is this?"},
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "aGk="}},
                    ],
                },
                "parent_tool_use_id": None,
            }
        ]

    def test_content_blocks(self):
        text_file = base64.b64encode(b"hello").decode()
        _, blocks = ClaudeRunner._process_requests(
            [
                AgentRequestImage(image_data="https://x/a.png", name="a"),
                AgentRequestFile(file_data="JVBE", name="a.pdf", mime_type="application/pdf"),
                AgentRequestFile(file_data=text_file, name="a.txt", mime_type="text/plain"),
                AgentRequestFile(file_data="https://x/a.pdf", name="b.pdf"),
            ]
        )
        assert blocks == [
            {"type": "image", "source": {"type": "url", "url": "https://x/a.png"}},
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "JVBE"}},
            {"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": "hello"}},
            {"type": "document", "source": {"type": "url", "url": "https://x/a.pdf"}},
        ]

    @pytest.mark.parametrize(
        "request_, message",
        [
            (AgentRequestImage(image_data="s3://b/k", name="a"), "s3://"),
            (AgentRequestImage(image_data="aGk=", name="a"), "mime_type is missing"),
            (AgentRequestFile(file_data="aGk=", name="a.zip", mime_type="application/zip"), "not supported"),
        ],
    )
    def test_unsupported_content_is_rejected(self, request_, message):
        with pytest.raises(ValueError, match=message):
            ClaudeRunner._process_requests([request_])


# --- stream --------------------------------------------------------------------------------------------


def _raw(event, parent=None):
    return StreamEvent(uuid="u", session_id="s", event=event, parent_tool_use_id=parent)


def _text_message(message_id="msg_1", text=("Hel", "lo")):
    return [
        _raw({"type": "message_start", "message": {"id": message_id}}),
        _raw({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
        *[_raw({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": t}}) for t in text],
        _raw({"type": "content_block_stop", "index": 0}),
        _raw({"type": "message_stop"}),
    ]


class TestStream:
    @pytest.mark.asyncio
    async def test_text_deltas_are_keyed_by_the_native_message_id(self, fake_client, runtime):
        agent = _module(_spec()).get_agent("general")
        fake_client.script = [*_text_message(), _result()]

        events = [e async for e in agent.runner.stream(agent, Session("s"), [AgentRequestText(prompt="hi")])]

        assert [e.type for e in events] == ["message_start", "text_delta", "text_delta", "message_end"]
        assert {e.message_id for e in events} == {"msg_1:0"}
        assert "".join(e.content for e in events if e.type == "text_delta") == "Hello"
        assert fake_client.instances[0].options.include_partial_messages is True

    @pytest.mark.asyncio
    async def test_thinking_and_tool_calls_map_with_native_ids_and_ak_tool_names(self, fake_client, runtime):
        agent = _module(_spec()).get_agent("general")
        fake_client.script = [
            _raw({"type": "message_start", "message": {"id": "msg_1"}}),
            _raw({"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}}),
            _raw({"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "hmm"}}),
            _raw({"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "sig"}}),
            _raw({"type": "content_block_stop", "index": 0}),
            _raw({"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "toolu_1", "name": "mcp__ak__double"}}),
            _raw({"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"x": 2}'}}),
            _raw({"type": "content_block_stop", "index": 1}),
            UserMessage(content=[ToolResultBlock(tool_use_id="toolu_1", content=[{"type": "text", "text": "4"}])]),
            _result(),
        ]

        events = [e async for e in agent.runner.stream(agent, Session("s"), [AgentRequestText(prompt="hi")])]

        assert [e.type for e in events] == [
            "reasoning_start",
            "reasoning_delta",
            "reasoning_end",
            "tool_call_start",
            "tool_call_args",
            "tool_call_end",
            "tool_call_result",
        ]
        start = events[3]
        assert (start.tool_call_id, start.name) == ("toolu_1", "double")
        assert events[4].delta == '{"x": 2}'
        assert (events[6].tool_call_id, events[6].content) == ("toolu_1", "4")

    @pytest.mark.asyncio
    async def test_subagent_traffic_is_not_emitted(self, fake_client, runtime):
        agent = _module(_spec()).get_agent("general")
        inner = [_raw(e.event, parent="toolu_task") for e in _text_message("msg_sub")]
        fake_client.script = [
            *inner,
            UserMessage(content=[ToolResultBlock(tool_use_id="x", content="r")], parent_tool_use_id="toolu_task"),
            _result(),
        ]

        events = [e async for e in agent.runner.stream(agent, Session("s"), [AgentRequestText(prompt="hi")])]

        assert events == []

    @pytest.mark.asyncio
    async def test_the_transcript_is_committed_after_a_full_drain(self, fake_client, runtime):
        agent = _module(_spec()).get_agent("general")
        session = Session("s")
        fake_client.script = [*_text_message(), _finish({"type": "user", "uuid": "u1"})]

        _ = [e async for e in agent.runner.stream(agent, session, [AgentRequestText(prompt="hi")])]

        assert session.get(FRAMEWORK).transcript("general")[""]

    @pytest.mark.asyncio
    async def test_an_error_result_raises_after_the_events(self, fake_client, runtime):
        agent = _module(_spec()).get_agent("general")
        fake_client.script = [*_text_message(), _result(is_error=True, subtype="error_during_execution", result=None)]

        events = []
        with pytest.raises(RuntimeError, match="error_during_execution"):
            async for event in agent.runner.stream(agent, Session("s"), [AgentRequestText(prompt="hi")]):
                events.append(event)
        assert [e.type for e in events][-1] == "message_end"

    @pytest.mark.asyncio
    async def test_closing_the_stream_early_disconnects_and_commits_nothing(self, fake_client, runtime):
        agent = _module(_spec()).get_agent("general")
        session = Session("s")
        fake_client.script = [*_text_message(), _mirror({"type": "user", "uuid": "u1"}), _result()]

        stream = agent.runner.stream(agent, session, [AgentRequestText(prompt="hi")])
        first = await stream.__anext__()
        await stream.aclose()

        assert first.type == "message_start"
        assert fake_client.instances[0].exited
        assert not session.get(FRAMEWORK).transcript("general")

    def test_mapper_closes_blocks_left_open(self):
        mapper = _ClaudeStreamMapper()
        for message in _text_message()[:3]:
            mapper.events(message)

        assert [e.type for e in mapper.close()] == ["message_end"]


# --- agent ---------------------------------------------------------------------------------------------


class TestAgent:
    @pytest.mark.parametrize(
        "declared, expected",
        [
            (None, "EXTRA"),
            ("Be brief.", "Be brief.\n\nEXTRA"),
            ({"type": "preset", "preset": "claude_code"}, {"type": "preset", "preset": "claude_code", "append": "EXTRA"}),
            ({"type": "preset", "preset": "claude_code", "append": "A"}, {"type": "preset", "preset": "claude_code", "append": "A\n\nEXTRA"}),
            ({"type": "custom", "prompt": "P"}, {"type": "custom", "prompt": "P\n\nEXTRA"}),
        ],
    )
    def test_override_system_prompt_appends_in_the_declared_form(self, runtime, declared, expected):
        agent = _module(_spec(system_prompt=declared)).get_agent("general")
        agent.override_system_prompt("EXTRA")
        assert agent.agent.options.system_prompt == expected

    def test_a_file_system_prompt_is_left_alone_with_a_warning(self, runtime, caplog):
        agent = _module(_spec(system_prompt={"type": "file", "path": "/p.md"})).get_agent("general")
        with caplog.at_level(logging.WARNING, logger="ak.claude.runner"):
            agent.override_system_prompt("EXTRA")
        assert agent.agent.options.system_prompt == {"type": "file", "path": "/p.md"}
        assert any("cannot be extended" in r.getMessage() for r in caplog.records)

    def test_shared_options_are_not_altered_through_one_declaration(self, runtime):
        shared = ClaudeAgentOptions(system_prompt="Base")
        module = _module(ClaudeAgentSpec(name="a", options=shared), ClaudeAgentSpec(name="b", options=shared))
        module.get_agent("a").override_system_prompt("ONLY-A")

        assert shared.system_prompt == "Base"
        assert module.get_agent("b").agent.options.system_prompt == "Base"

    def test_a_shared_tool_list_is_not_altered_through_one_declaration(self, runtime):
        shared = ClaudeToolBuilder.bind([double])
        module = _module(ClaudeAgentSpec(name="a", tools=shared), ClaudeAgentSpec(name="b", tools=shared))
        module.get_agent("a").attach_tool(_echo)

        assert [t.name for t in shared] == ["double"]
        assert [t.name for t in module.get_agent("b").agent.tools] == ["double"]

    def test_description_falls_back_to_a_string_system_prompt(self, runtime):
        module = _module(ClaudeAgentSpec(name="a", options=ClaudeAgentOptions(system_prompt="You plan trips.")))
        assert module.get_agent("a").get_description() == "You plan trips."

    def test_attach_tool_skips_a_name_already_present(self, runtime):
        spec = _spec()
        spec.tools = ClaudeToolBuilder.bind([double])
        agent = _module(spec).get_agent("general")

        agent.attach_tool(double)

        assert [t.name for t in agent.agent.tools] == ["double"]

    def test_module_requires_a_name(self, runtime):
        with pytest.raises(ValueError, match="must have a name"):
            _module(ClaudeAgentSpec(name=""))

    def test_supports_pause_and_streaming(self):
        assert ClaudeRunner().supports_pause is True
        assert ClaudeRunner().supports_streaming is True


# --- subagents -----------------------------------------------------------------------------------------


class TestSubagents:
    @staticmethod
    def _options(agent):
        claude_session = ClaudeSession()
        return agent.runner._native_options(agent, {}, claude_session, _ClaudeSessionStore(claude_session, agent.name), stream=False)

    def test_native_subagent_fields_and_parent_tools_are_preserved(self, runtime):
        weather = AgentDefinition(
            description="Weather questions", prompt="Use get_weather.", tools=["mcp__ak__double"], model="haiku", maxTurns=4, skills=["forecast"]
        )
        triage = ClaudeAgentSpec(
            name="triage",
            options=ClaudeAgentOptions(tools=[], allowed_tools=["Read"], agents={"weather": weather}),
            tools=ClaudeToolBuilder.bind([double]),
        )
        agent = _module(triage).get_agent("triage")

        options = self._options(agent)

        assert options.agents["weather"] is weather
        assert options.agents["weather"].maxTurns == 4
        assert options.agents["weather"].skills == ["forecast"]
        assert AK_MCP_SERVER in options.mcp_servers
        assert options.tools == ["Agent"]
        assert options.allowed_tools == ["Read", "mcp__ak__double", "Agent"]
        assert agent.agent.options.tools == [] and agent.agent.options.agents == {"weather": weather}

    def test_a_subagent_with_default_tools_inherits_the_sessions_tools(self, runtime):
        triage = ClaudeAgentSpec(name="triage", options=ClaudeAgentOptions(agents={"helper": AgentDefinition(description="helper", prompt="Help.")}))

        options = self._options(_module(triage).get_agent("triage"))

        assert options.agents["helper"].tools is None
        assert options.agents["helper"].description == "helper"
        assert options.tools is None  # the full built-in toolset, which already includes Agent

    def test_native_agent_remains_available_after_per_run_override(self, runtime):
        native = AgentDefinition(description="Native", prompt="P", permissionMode="dontAsk")
        triage = ClaudeAgentSpec(name="triage", options=ClaudeAgentOptions(tools=[], agents={"native": native}))
        agent = _module(triage).get_agent("triage")
        agent.run_options["model"] = "sonnet"

        options = self._options(agent)

        assert options.agents["native"] is native
        assert options.tools == ["Agent"]


# --- human in the loop ----------------------------------------------------------------------------------


def _gated_spec(name="gated", tool_name="echo", needs_approval=True):
    spec = _spec(name)
    spec.tools = ClaudeToolBuilder.bind([_echo], needs_approval=needs_approval)
    if tool_name != "echo":
        spec.tools[0].name = tool_name
    return spec


def _defer(tool_use_id="tu-1", name="echo", arguments=None, **result_kwargs):
    """A script step yielding a ResultMessage that defers one tool call, stamped with the run's session id.
    Mirrors one entry first, as a real turn always does (at minimum the user message), so the next turn
    correctly resumes rather than reading an empty transcript as "no prior turn"."""
    deferred = DeferredToolUse(id=tool_use_id, name=ClaudeToolBuilder.mcp_tool_name(name), input=arguments or {})

    async def step(client):
        await client.options.session_store.append({"project_key": "p", "session_id": client.session_id}, [{"type": "user", "uuid": tool_use_id}])
        return ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id=client.session_id,
            result=None,
            deferred_tool_use=deferred,
            **result_kwargs,
        )

    return step


def _resume_requests(*decisions, prompt=None):
    requests = [AgentRequestText(prompt=prompt)] if prompt else []
    return requests + [AgentResumeRequestAny(decisions=list(decisions))], list(decisions)


class TestHITLDecisionHook:
    """`_decision_hook`/`_hook_decision` directly: the combined PreToolUse hook and the verb mapping,
    independent of a full run."""

    @pytest.mark.asyncio
    async def test_a_gated_tool_defers_on_its_first_attempt(self):
        hook = ClaudeRunner()._decision_hook(frozenset({"mcp__ak__echo"}), None)
        out = await hook({"tool_name": "mcp__ak__echo"}, "tu-1", {})
        assert out == {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "defer"}}

    @pytest.mark.asyncio
    async def test_an_ungated_tool_is_left_alone(self):
        hook = ClaudeRunner()._decision_hook(frozenset(), None)
        assert await hook({"tool_name": "mcp__ak__other"}, "tu-1", {}) == {}

    @pytest.mark.asyncio
    async def test_the_resumed_call_s_own_decision_wins_over_the_standing_gate(self):
        decision = ResumeDecision(id="x", status="approved")
        hook = ClaudeRunner()._decision_hook(frozenset({"mcp__ak__echo"}), ("tu-1", decision))
        out = await hook({"tool_name": "mcp__ak__echo"}, "tu-1", {})
        assert out["hookSpecificOutput"]["permissionDecision"] == "allow"

    @pytest.mark.asyncio
    async def test_a_different_pending_call_still_defers_while_one_is_being_resumed(self):
        """The precedence fix: only the resumed call's own id bypasses the standing gate."""
        decision = ResumeDecision(id="x", status="approved")
        hook = ClaudeRunner()._decision_hook(frozenset({"mcp__ak__echo"}), ("tu-1", decision))
        out = await hook({"tool_name": "mcp__ak__echo"}, "tu-2", {})
        assert out["hookSpecificOutput"]["permissionDecision"] == "defer"

    def test_approved_payload_becomes_updated_input(self):
        decision = ResumeDecision(id="x", status="approved", payload={"text": "override"})
        out = ClaudeRunner()._hook_decision(decision)
        assert out == {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow", "updatedInput": {"text": "override"}}}

    def test_approved_without_a_payload_carries_no_updated_input(self):
        out = ClaudeRunner()._hook_decision(ResumeDecision(id="x", status="approved"))
        assert out == {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}

    def test_denied_carries_the_human_s_message(self):
        out = ClaudeRunner()._hook_decision(ResumeDecision(id="x", status="denied", message="too expensive"))
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert out["hookSpecificOutput"]["permissionDecisionReason"] == "too expensive"

    def test_cancelled_does_not_read_as_a_refusal(self):
        out = ClaudeRunner()._hook_decision(ResumeDecision(id="x", status="cancelled"))
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert out["hookSpecificOutput"]["permissionDecisionReason"] == ClaudeRunner.CANCELLED_DECISION_MESSAGE


class TestHITLPauseDetection:
    def test_the_runner_declares_the_capability(self):
        assert ClaudeRunner().supports_pause is True

    @pytest.mark.asyncio
    async def test_a_deferred_call_returns_a_paused_reply(self, fake_client, runtime):
        agent = _module(_gated_spec()).get_agent("gated")
        fake_client.script = [_defer(arguments={"text": "hi"})]

        reply = await agent.runner.run(agent, Session("s"), [AgentRequestText(prompt="hi")])

        assert isinstance(reply, AgentPausedReplyAny)
        assert reply.interruptions[0].kind == "tool_call"
        assert reply.interruptions[0].tool_name == "echo"
        assert reply.interruptions[0].arguments == '{"text": "hi"}'

    @pytest.mark.asyncio
    async def test_a_gated_tool_is_approved_automatically_everywhere_else(self, fake_client, runtime):
        """Only the gated tool defers; an ungated tool bound alongside it is approved like any other."""
        agent = _module(_gated_spec()).get_agent("gated")
        fake_client.script = [_result()]

        await agent.runner.run(agent, Session("s"), [AgentRequestText(prompt="hi")])

        options = fake_client.instances[0].options
        assert "mcp__ak__echo" not in options.allowed_tools

    @pytest.mark.asyncio
    async def test_permission_bypass_cannot_execute_a_gated_tool_without_a_decision(self, fake_client, runtime):
        calls = []

        async def charge(amount: int) -> str:
            calls.append(amount)
            return "charged"

        spec = _spec(permission_mode="bypassPermissions", allowed_tools=["mcp__ak__charge"])
        spec.tools = ClaudeToolBuilder.bind([charge], needs_approval=True)
        agent = _module(spec).get_agent("general")
        seen = []

        async def attempt(client):
            seen.append(await spec.tools[0].handler({"amount": 5}))

        fake_client.script = [attempt, _result()]
        await agent.runner.run(agent, Session("s"), [AgentRequestText(prompt="charge")])

        assert calls == []
        assert seen[0]["isError"] is True

    @pytest.mark.asyncio
    async def test_the_record_can_be_found_and_survives_a_pickle(self, fake_client, runtime):
        import pickle

        agent = _module(_gated_spec()).get_agent("gated")
        session = Session("s")
        fake_client.script = [_defer()]

        reply = await agent.runner.run(agent, session, [AgentRequestText(prompt="hi")])

        record = PausedRunState.get(pickle.loads(pickle.dumps(session)), reply.run_id)
        assert record is not None
        assert record.payload["tool_use_id"] == "tu-1"
        assert record.payload["session_id"] == session.get("claude").session_id("gated")
        assert record.payload["main_entries"] == 1

    @pytest.mark.asyncio
    async def test_it_replaces_only_its_own_framework_s_pause(self, fake_client, runtime):
        from agentkernel.core.event import PausedInterruption

        agent = _module(_gated_spec()).get_agent("gated")
        session = Session("s")
        foreign = PausedRunState.add(
            session, agent="support", runner="openai", interruptions=[PausedInterruption(id="openai-1", kind="tool_call", tool_name="issue_refund")]
        )

        fake_client.script = [_defer()]
        await agent.runner.run(agent, session, [AgentRequestText(prompt="hi")])

        assert foreign.id in [r.id for r in PausedRunState.list(session)]
        assert [r.runner for r in PausedRunState.list(session) if r.id != foreign.id] == ["claude"]


class TestHITLResume:
    @pytest.mark.asyncio
    async def test_another_turn_invalidates_a_pending_resume(self, fake_client, runtime):
        agent = _module(_gated_spec()).get_agent("gated")
        session = Session("s")
        fake_client.script = [_defer()]
        paused = await agent.runner.run(agent, session, [AgentRequestText(prompt="first")])
        record = PausedRunState.get(session, paused.run_id)
        fake_client.script = [_finish({"type": "assistant", "uuid": "later"})]
        await agent.runner.run(agent, session, [AgentRequestText(prompt="another turn")])
        requests, decisions = _resume_requests(ResumeDecision(id=paused.interruptions[0].id, status="approved"))

        with pytest.raises(ValueError, match="conversation changed"):
            await agent.runner.resume(agent, session, requests, decisions, record)

    @pytest.mark.asyncio
    async def test_approved_tool_call_is_allowed_once_with_matching_arguments(self, fake_client, runtime):
        calls = []

        async def charge(amount: int) -> str:
            calls.append(amount)
            return "charged"

        spec = _spec()
        spec.tools = ClaudeToolBuilder.bind([charge], needs_approval=True)
        agent = _module(spec).get_agent("general")
        session = Session("s")
        fake_client.script = [_defer(name="charge", arguments={"amount": 5})]
        paused = await agent.runner.run(agent, session, [AgentRequestText(prompt="charge")])
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests(ResumeDecision(id=paused.interruptions[0].id, status="approved"))
        seen = []

        async def execute(client):
            hook = client.options.hooks["PreToolUse"][-1].hooks[0]
            await hook({"tool_name": "mcp__ak__charge", "tool_input": {"amount": 5}}, "tu-1", {})
            seen.append(await spec.tools[0].handler({"amount": 5}))
            seen.append(await spec.tools[0].handler({"amount": 5}))

        fake_client.script = [execute, _finish(result="done")]
        await agent.runner.resume(agent, session, requests, decisions, record)

        assert calls == [5]
        assert "isError" not in seen[0]
        assert seen[1]["isError"] is True

    @pytest.mark.asyncio
    async def test_a_successful_resume_clears_its_record_and_returns_the_reply(self, fake_client, runtime):
        agent = _module(_gated_spec()).get_agent("gated")
        session = Session("s")
        fake_client.script = [_defer()]
        paused = await agent.runner.run(agent, session, [AgentRequestText(prompt="hi")])
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests(ResumeDecision(id=paused.interruptions[0].id, status="approved"))

        fake_client.script = [_finish({"type": "assistant", "uuid": "a-1"}, result="done")]
        reply = await agent.runner.resume(agent, session, requests, decisions, record)

        assert isinstance(reply, AgentReplyText)
        assert reply.response == "done"
        assert PausedRunState.list(session) == []

    @pytest.mark.asyncio
    async def test_the_resumed_call_carries_resume_as_the_claude_session(self, fake_client, runtime):
        agent = _module(_gated_spec()).get_agent("gated")
        session = Session("s")
        fake_client.script = [_defer()]
        paused = await agent.runner.run(agent, session, [AgentRequestText(prompt="hi")])
        first_session_id = fake_client.instances[0].options.session_id
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests(ResumeDecision(id=paused.interruptions[0].id, status="approved"))

        fake_client.script = [_finish(result="done")]
        await agent.runner.resume(agent, session, requests, decisions, record)

        assert fake_client.instances[1].options.resume == first_session_id
        assert fake_client.instances[1].options.session_id is None

    @pytest.mark.asyncio
    async def test_the_resume_hook_is_wired_to_this_decision(self, fake_client, runtime):
        agent = _module(_gated_spec()).get_agent("gated")
        session = Session("s")
        fake_client.script = [_defer()]
        paused = await agent.runner.run(agent, session, [AgentRequestText(prompt="hi")])
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests(ResumeDecision(id=paused.interruptions[0].id, status="denied", message="no"))

        fake_client.script = [_finish(result="done")]
        await agent.runner.resume(agent, session, requests, decisions, record)

        hooks = fake_client.instances[1].options.hooks["PreToolUse"]
        out = await hooks[-1].hooks[0]({"tool_name": "mcp__ak__echo"}, "tu-1", {})
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert out["hookSpecificOutput"]["permissionDecisionReason"] == "no"

    @pytest.mark.asyncio
    async def test_framework_context_survives_a_resume(self, fake_client, runtime):
        agent = _module(_gated_spec()).get_agent("gated")
        session = Session("s")
        session.set_framework_context({"user_id": "42"})
        fake_client.script = [_defer()]
        paused = await agent.runner.run(agent, session, [AgentRequestText(prompt="hi")])
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests(ResumeDecision(id=paused.interruptions[0].id, status="approved"))

        fake_client.script = [_finish(result="done")]
        await agent.runner.resume(agent, session, requests, decisions, record)

        assert session.get_framework_context() == {"user_id": "42"}

    @pytest.mark.asyncio
    async def test_a_re_deferred_call_on_resume_supersedes_the_record(self, fake_client, runtime):
        agent = _module(_gated_spec()).get_agent("gated")
        session = Session("s")
        fake_client.script = [_defer()]
        paused = await agent.runner.run(agent, session, [AgentRequestText(prompt="hi")])
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests(ResumeDecision(id=paused.interruptions[0].id, status="approved"))

        fake_client.script = [_defer(tool_use_id="tu-2")]
        reply = await agent.runner.resume(agent, session, requests, decisions, record)

        assert isinstance(reply, AgentPausedReplyAny)
        records = PausedRunState.list(session)
        assert len(records) == 1 and records[0].id != record.id

    @pytest.mark.asyncio
    async def test_a_failed_resume_keeps_its_record(self, fake_client, runtime):
        agent = _module(_gated_spec()).get_agent("gated")
        session = Session("s")
        fake_client.script = [_defer()]
        paused = await agent.runner.run(agent, session, [AgentRequestText(prompt="hi")])
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests(ResumeDecision(id=paused.interruptions[0].id, status="approved"))

        fake_client.script = [_result(is_error=True, subtype="error_max_turns")]
        reply = await agent.runner.resume(agent, session, requests, decisions, record)

        assert isinstance(reply, AgentReplyText)
        assert PausedRunState.get(session, paused.run_id) is not None

    @pytest.mark.asyncio
    async def test_resume_stream_ends_in_run_paused_when_deferred_again(self, fake_client, runtime):
        agent = _module(_gated_spec()).get_agent("gated")
        session = Session("s")
        fake_client.script = [_defer()]
        paused = await agent.runner.run(agent, session, [AgentRequestText(prompt="hi")])
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests(ResumeDecision(id=paused.interruptions[0].id, status="approved"))

        fake_client.script = [_defer(tool_use_id="tu-2")]
        events = [event async for event in agent.runner.resume_stream(agent, session, requests, decisions, record)]

        assert isinstance(events[-1], RunPaused)

    @pytest.mark.asyncio
    async def test_resume_stream_clears_its_record_on_success(self, fake_client, runtime):
        agent = _module(_gated_spec()).get_agent("gated")
        session = Session("s")
        fake_client.script = [_defer()]
        paused = await agent.runner.run(agent, session, [AgentRequestText(prompt="hi")])
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests(ResumeDecision(id=paused.interruptions[0].id, status="approved"))

        fake_client.script = [_finish(result="done")]
        events = [event async for event in agent.runner.resume_stream(agent, session, requests, decisions, record)]

        assert PausedRunState.list(session) == []
        assert not any(isinstance(e, RunPaused) for e in events)


class TestHITLRejectsAnUnanswerableResume:
    """Raised above the adapter's `try`, since the `except Exception` below would otherwise flatten the message."""

    @pytest.mark.asyncio
    async def test_more_than_one_decision_is_refused(self, fake_client, runtime):
        agent = _module(_gated_spec()).get_agent("gated")
        session = Session("s")
        fake_client.script = [_defer()]
        paused = await agent.runner.run(agent, session, [AgentRequestText(prompt="hi")])
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests(
            ResumeDecision(id=paused.interruptions[0].id, status="approved"), ResumeDecision(id="extra", status="approved")
        )

        with pytest.raises(ValueError, match="single pending tool call"):
            await agent.runner.resume(agent, session, requests, decisions, record)
        assert PausedRunState.get(session, paused.run_id) is not None

    @pytest.mark.asyncio
    async def test_a_non_object_approval_payload_is_refused(self, fake_client, runtime):
        agent = _module(_gated_spec()).get_agent("gated")
        session = Session("s")
        fake_client.script = [_defer()]
        paused = await agent.runner.run(agent, session, [AgentRequestText(prompt="hi")])
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests(ResumeDecision(id=paused.interruptions[0].id, status="approved", payload="large"))

        with pytest.raises(ValueError, match="only carry a JSON object"):
            await agent.runner.resume(agent, session, requests, decisions, record)


# --- telemetry --------------------------------------------------------------------------------------


class TestClaudeTelemetry:
    """`ClaudeTelemetry.enable_traces()` is a pure helper: no live CLI, no OTel collector, no network
    needed to verify it builds the right env dict and never touches anything outside its return value."""

    def test_defaults_enable_the_beta_trace_export_over_otlp(self):
        env = ClaudeTelemetry.enable_traces()

        assert env["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"
        assert env["CLAUDE_CODE_ENHANCED_TELEMETRY_BETA"] == "1"
        assert env["OTEL_TRACES_EXPORTER"] == "otlp"
        assert env["OTEL_EXPORTER_OTLP_PROTOCOL"] == "http/protobuf"
        assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in env
        assert "OTEL_EXPORTER_OTLP_HEADERS" not in env

    def test_endpoint_and_headers_are_included_when_given(self):
        env = ClaudeTelemetry.enable_traces(endpoint="http://collector:4318", headers="Authorization=Bearer t")

        assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://collector:4318"
        assert env["OTEL_EXPORTER_OTLP_HEADERS"] == "Authorization=Bearer t"

    def test_protocol_is_overridable(self):
        env = ClaudeTelemetry.enable_traces(protocol="grpc")
        assert env["OTEL_EXPORTER_OTLP_PROTOCOL"] == "grpc"

    def test_extra_env_is_passed_through_verbatim(self):
        env = ClaudeTelemetry.enable_traces(OTEL_SERVICE_NAME="my-agent")
        assert env["OTEL_SERVICE_NAME"] == "my-agent"

    def test_extra_env_can_override_a_built_in_key(self):
        """The caller has the last word on any key, including ones this helper sets itself."""
        env = ClaudeTelemetry.enable_traces(OTEL_TRACES_EXPORTER="console")
        assert env["OTEL_TRACES_EXPORTER"] == "console"

    def test_never_reads_or_mutates_the_process_environment(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://should-not-be-read:4318")
        env = ClaudeTelemetry.enable_traces()
        assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in env
        assert os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://should-not-be-read:4318"

    def test_returns_a_fresh_dict_each_call(self):
        """The caller merges this into their own env=; it must never be a shared mutable object."""
        first = ClaudeTelemetry.enable_traces()
        first["CLAUDE_CODE_ENABLE_TELEMETRY"] = "mutated"
        second = ClaudeTelemetry.enable_traces()
        assert second["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"
