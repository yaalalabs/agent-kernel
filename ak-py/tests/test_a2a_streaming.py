"""Tests for A2A v1.0.0 compatibility and SSE streaming."""
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentkernel.core.base import Runner, Session
from agentkernel.core.model import AgentReply, AgentRequest, StreamChunk


# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------

class _BaseRunner(Runner):
    def __init__(self):
        super().__init__("test")

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        raise NotImplementedError()

    async def stream(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AsyncGenerator[str, None]:
        raise NotImplementedError()
        yield


# ---------------------------------------------------------------------------
# Phase 2.1 — base Runner.supports_streaming defaults to True
# ---------------------------------------------------------------------------

def test_runner_supports_streaming_default():
    runner = _BaseRunner()
    assert runner.supports_streaming is True


# ---------------------------------------------------------------------------
# Phase 2.2 — CrewAI and Smolagents return False
# ---------------------------------------------------------------------------

def test_crewai_runner_supports_streaming_false():
    from agentkernel.framework.crewai.crewai import CrewAIRunner

    runner = CrewAIRunner()
    assert runner.supports_streaming is False


def test_smolagents_runner_supports_streaming_false():
    from agentkernel.framework.smolagents.smolagents import SmolagentsRunner

    runner = SmolagentsRunner()
    assert runner.supports_streaming is False


# ---------------------------------------------------------------------------
# Phase 1.3 / 2.3 — A2ACardBuilder produces correct protobuf card
# ---------------------------------------------------------------------------

def test_a2a_card_builder_streaming_flag():
    from agentkernel.core.builder import A2ACardBuilder
    from a2a.types import AgentSkill

    with patch("agentkernel.core.builder.AKConfig") as mock_cfg:
        mock_cfg.get.return_value.a2a.url = "http://localhost:8080"
        mock_cfg.get.return_value.library_version = "0.1.0"

        skill = AgentSkill(id="search", name="search", description="Search the web")
        card = A2ACardBuilder.build(
            name="my-agent",
            description="A test agent",
            skills=[skill],
            streaming=True,
        )

    assert card.capabilities.streaming is True
    assert card.name == "my-agent"


def test_a2a_card_builder_no_streaming_by_default():
    from agentkernel.core.builder import A2ACardBuilder

    with patch("agentkernel.core.builder.AKConfig") as mock_cfg:
        mock_cfg.get.return_value.a2a.url = "http://localhost:8080"
        mock_cfg.get.return_value.library_version = "0.1.0"

        card = A2ACardBuilder.build(name="agent", description="desc", skills=[])

    assert card.capabilities.streaming is False


# ---------------------------------------------------------------------------
# Phase 2.4 — Executor.execute() streaming path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_executor_streaming_path():
    from agentkernel.api.a2a.a2a import A2A
    from a2a.server.agent_execution import RequestContext
    from a2a.server.events import EventQueue

    agent_name = "streaming-agent"
    executor = A2A.Executor(agent_name)

    # Mock agent that supports streaming
    mock_runner = MagicMock()
    mock_runner.supports_streaming = True
    mock_agent = MagicMock()
    mock_agent.runner = mock_runner

    mock_context = MagicMock(spec=RequestContext)
    mock_context.task_id = "task-1"
    mock_context.context_id = "ctx-1"
    mock_context.message = MagicMock()
    mock_context.get_user_input.return_value = "hello"

    mock_event_queue = MagicMock(spec=EventQueue)

    chunks = [StreamChunk(delta="Hello"), StreamChunk(delta=" world"), StreamChunk(done=True)]

    async def mock_stream_multi(requests):
        for chunk in chunks:
            yield chunk

    mock_updater = AsyncMock()

    with (
        patch("agentkernel.api.a2a.a2a.Runtime") as mock_runtime,
        patch("agentkernel.api.a2a.a2a.AgentService") as mock_service_cls,
        patch("agentkernel.api.a2a.a2a.TaskUpdater", return_value=mock_updater),
    ):
        mock_runtime.current.return_value.agents.return_value.get.return_value = mock_agent
        mock_service = MagicMock()
        mock_service.stream_multi = mock_stream_multi
        mock_service_cls.return_value = mock_service

        await executor.execute(mock_context, mock_event_queue)

    mock_updater.start_work.assert_awaited_once()
    assert mock_updater.add_artifact.await_count == 2  # two non-empty delta chunks
    first_call = mock_updater.add_artifact.await_args_list[0]
    second_call = mock_updater.add_artifact.await_args_list[1]
    assert first_call.kwargs["last_chunk"] is False
    assert second_call.kwargs["last_chunk"] is True
    mock_updater.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_executor_streaming_enqueues_task_before_status_update():
    from agentkernel.api.a2a.a2a import A2A
    from a2a.server.agent_execution import RequestContext
    from a2a.server.events import EventQueue

    agent_name = "streaming-agent"
    executor = A2A.Executor(agent_name)

    mock_runner = MagicMock()
    mock_runner.supports_streaming = True
    mock_agent = MagicMock()
    mock_agent.runner = mock_runner

    mock_context = MagicMock(spec=RequestContext)
    mock_context.task_id = "task-1"
    mock_context.context_id = "ctx-1"
    mock_context.current_task = None
    mock_context.message = MagicMock()
    mock_context.get_user_input.return_value = "hello"

    mock_event_queue = MagicMock(spec=EventQueue)
    call_order: list[str] = []

    async def enqueue_event(event):
        call_order.append(f"enqueue:{type(event).__name__}")

    async def mock_stream_multi(requests):
        yield StreamChunk(delta="Hello")
        yield StreamChunk(done=True)

    mock_updater = AsyncMock()
    mock_updater.start_work.side_effect = lambda *args, **kwargs: call_order.append("start_work")
    mock_updater.add_artifact = AsyncMock()
    mock_updater.complete = AsyncMock()
    mock_updater.failed = AsyncMock()

    with (
        patch("agentkernel.api.a2a.a2a.Runtime") as mock_runtime,
        patch("agentkernel.api.a2a.a2a.AgentService") as mock_service_cls,
        patch("agentkernel.api.a2a.a2a.TaskUpdater", return_value=mock_updater),
        patch("agentkernel.api.a2a.a2a.new_task_from_user_message", return_value=MagicMock(name="task")) as mock_new_task,
    ):
        mock_runtime.current.return_value.agents.return_value.get.return_value = mock_agent
        mock_service = MagicMock()
        mock_service.stream_multi = mock_stream_multi
        mock_service_cls.return_value = mock_service
        mock_event_queue.enqueue_event.side_effect = enqueue_event

        await executor.execute(mock_context, mock_event_queue)

    mock_new_task.assert_called_once_with(mock_context.message)
    assert call_order[0].startswith("enqueue:")
    assert call_order[1] == "start_work"


@pytest.mark.asyncio
async def test_executor_streaming_marks_failed_on_runtime_error_chunk():
    from agentkernel.api.a2a.a2a import A2A
    from a2a.server.agent_execution import RequestContext
    from a2a.server.events import EventQueue

    agent_name = "streaming-agent"
    executor = A2A.Executor(agent_name)

    mock_runner = MagicMock()
    mock_runner.supports_streaming = True
    mock_agent = MagicMock()
    mock_agent.runner = mock_runner

    mock_context = MagicMock(spec=RequestContext)
    mock_context.task_id = "task-1"
    mock_context.context_id = "ctx-1"
    mock_context.message = MagicMock()
    mock_context.get_user_input.return_value = "hello"

    mock_event_queue = MagicMock(spec=EventQueue)

    async def mock_stream_multi(requests):
        yield StreamChunk(error="stream broke", done=True)

    mock_updater = AsyncMock()

    with (
        patch("agentkernel.api.a2a.a2a.Runtime") as mock_runtime,
        patch("agentkernel.api.a2a.a2a.AgentService") as mock_service_cls,
        patch("agentkernel.api.a2a.a2a.TaskUpdater", return_value=mock_updater),
    ):
        mock_runtime.current.return_value.agents.return_value.get.return_value = mock_agent
        mock_service = MagicMock()
        mock_service.stream_multi = mock_stream_multi
        mock_service_cls.return_value = mock_service

        await executor.execute(mock_context, mock_event_queue)

    mock_updater.start_work.assert_awaited_once()
    mock_updater.add_artifact.assert_not_awaited()
    mock_updater.complete.assert_not_awaited()
    mock_updater.failed.assert_awaited_once()


# ---------------------------------------------------------------------------
# Phase 2.4 — Executor.execute() blocking path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_executor_blocking_path():
    from agentkernel.api.a2a.a2a import A2A
    from a2a.server.agent_execution import RequestContext
    from a2a.server.events import EventQueue

    agent_name = "blocking-agent"
    executor = A2A.Executor(agent_name)

    mock_runner = MagicMock()
    mock_runner.supports_streaming = False
    mock_agent = MagicMock()
    mock_agent.runner = mock_runner

    mock_context = MagicMock(spec=RequestContext)
    mock_context.task_id = "task-2"
    mock_context.context_id = "ctx-2"
    mock_context.message = MagicMock()
    mock_context.get_user_input.return_value = "hello"

    mock_event_queue = AsyncMock(spec=EventQueue)

    with (
        patch("agentkernel.api.a2a.a2a.Runtime") as mock_runtime,
        patch("agentkernel.api.a2a.a2a.AgentService") as mock_service_cls,
        patch("agentkernel.api.a2a.a2a.new_text_message", return_value=MagicMock()),
    ):
        mock_runtime.current.return_value.agents.return_value.get.return_value = mock_agent
        mock_service = AsyncMock()
        mock_service.run = AsyncMock(return_value="The answer")
        mock_service_cls.return_value = mock_service

        await executor.execute(mock_context, mock_event_queue)

    mock_service.run.assert_awaited_once_with(prompt="hello")
    mock_event_queue.enqueue_event.assert_awaited_once()
