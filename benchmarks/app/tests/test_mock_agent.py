import runpy
from pathlib import Path
from unittest.mock import MagicMock

import mock_agent
import pytest
from agentkernel.core.base import Session
from agentkernel.core.model import AgentReplyAny, AgentRequestText
from agentkernel.core.runtime import Runtime
from mock_agent import AGENT_NAME, MockAgent, MockRunner

APP = Path(__file__).resolve().parent.parent / "agent.py"
MIN, MAX = "AK_BENCH_MOCK_AGENT_MIN_DELAY_S", "AK_BENCH_MOCK_AGENT_MAX_DELAY_S"


@pytest.fixture
def delays(monkeypatch):
    monkeypatch.setenv(MIN, "0.5")
    monkeypatch.setenv(MAX, "1.5")


@pytest.fixture
def sleeps(monkeypatch):
    recorded = []

    async def fake_sleep(seconds):
        recorded.append(seconds)

    monkeypatch.setattr(mock_agent.asyncio, "sleep", fake_sleep)
    return recorded


@pytest.fixture
def clean_runtime():
    yield
    agent = Runtime.current().agents().get(AGENT_NAME)
    if agent is not None:
        Runtime.current().deregister(agent)


@pytest.mark.asyncio
async def test_run_sleeps_within_bounds_and_echoes(delays, sleeps):
    runner = MockRunner()
    session = MagicMock(spec=Session)
    reply = await runner.run(None, session, [AgentRequestText(prompt="req-42 hello")])
    assert isinstance(reply, AgentReplyAny)
    assert reply.content == {"echo": "req-42 hello"}
    assert len(sleeps) == 1 and 0.5 <= sleeps[0] <= 1.5
    assert session.mock_calls == []


@pytest.mark.asyncio
async def test_delays_stay_within_bounds_over_many_draws(delays, sleeps):
    runner = MockRunner()
    for _ in range(500):
        await runner.run(None, MagicMock(spec=Session), [AgentRequestText(prompt="x")])
    assert all(0.5 <= s <= 1.5 for s in sleeps)
    assert min(sleeps) < 0.7 and max(sleeps) > 1.3


@pytest.mark.asyncio
async def test_no_text_request_echoes_empty(delays, sleeps):
    reply = await MockRunner().run(None, MagicMock(spec=Session), [])
    assert reply.content == {"echo": ""}


@pytest.mark.asyncio
async def test_stream_yields_one_echo_delta(delays, sleeps):
    events = [e async for e in MockRunner().stream(None, MagicMock(spec=Session), [AgentRequestText(prompt="hi")])]
    assert [e.type for e in events] == ["message_start", "text_delta", "message_end"]
    assert events[1].content == "hi"
    assert len({e.message_id for e in events}) == 1
    assert len(sleeps) == 1


@pytest.mark.asyncio
async def test_variables_read_once_at_creation(delays, sleeps, monkeypatch):
    runner = MockRunner()
    monkeypatch.setenv(MIN, "100")
    monkeypatch.setenv(MAX, "200")
    await runner.run(None, MagicMock(spec=Session), [AgentRequestText(prompt="x")])
    assert 0.5 <= sleeps[0] <= 1.5


def test_agent_registers_mock_agent_with_both_variables(delays, clean_runtime):
    runpy.run_path(str(APP))
    assert isinstance(Runtime.current().agents()[AGENT_NAME], MockAgent)


def test_agent_registers_real_agent_with_neither(monkeypatch, clean_runtime):
    monkeypatch.delenv(MIN, raising=False)
    monkeypatch.delenv(MAX, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    runpy.run_path(str(APP))
    agent = Runtime.current().agents()[AGENT_NAME]
    assert not isinstance(agent, MockAgent)


@pytest.mark.parametrize("set_var, unset_var", [(MIN, MAX), (MAX, MIN)])
def test_agent_raises_with_only_one_variable(monkeypatch, clean_runtime, set_var, unset_var):
    monkeypatch.setenv(set_var, "1")
    monkeypatch.setenv(unset_var, "")
    with pytest.raises(RuntimeError, match="set both"):
        runpy.run_path(str(APP))
    assert AGENT_NAME not in Runtime.current().agents()
