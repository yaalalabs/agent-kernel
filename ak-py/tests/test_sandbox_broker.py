"""Broker-flavor mechanics for the sandbox capability: ``embedded`` and ``thread`` flavors
end-to-end, the thread flavor's loop-identity contract, wait-policy promotion with
late-completion recovery, and suspend/resume completion ingestion through ``Runtime.run``.

The AWS ``sqs`` flavor (DB-first delivery, offload, fail-fast ceiling) is covered when it
lands in a later iteration.
"""

import asyncio
import json
import threading
import time

import pytest

from agentkernel import Agent, Runner
from agentkernel.core.config import AKConfig, _ExecutionBrokerConfig, _GuardrailConfig, _SandboxConfig, _SandboxPolicyConfig, _SandboxProfileConfig
from agentkernel.core.model import AgentReplyText, AgentRequestAny, AgentRequestText
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.sandbox.broker.base import ExecutionCompletion
from agentkernel.sandbox.broker.thread import ThreadBroker
from agentkernel.sandbox.errors import SandboxConfigError, SandboxPolicyError
from agentkernel.sandbox.factory import ExecutionBrokerFactory, SandboxProviderFactory
from agentkernel.sandbox.manager import ExecutionManager
from agentkernel.sandbox.model import SandboxResult, SandboxSession, SandboxTask
from agentkernel.sandbox.testing import FakeSandbox, FakeSandboxProvider
from agentkernel.sandbox.tools import check_sandbox_task, run_code

FAKE_DOTTED = "agentkernel.sandbox.testing.FakeSandboxProvider"


def _stop_leaked_broker():
    """Synchronously stop the current manager's thread broker so its daemon thread + private
    event loop don't leak across tests (only ThreadBroker.close() joins the thread, and it's
    async — here we drive the same shutdown from a sync fixture teardown)."""
    mgr = ExecutionManager._instance
    broker = getattr(mgr, "_broker", None) if mgr is not None else None
    thread = getattr(broker, "_thread", None)
    if thread is not None and thread.is_alive():
        broker._closed = True
        broker._loop.call_soon_threadsafe(broker._queue.put_nowait, None)
        thread.join(5.0)


@pytest.fixture(autouse=True)
def reset_singletons():
    AKConfig._reset()
    ExecutionManager._reset()
    SandboxProviderFactory._reset()
    Runtime._system_pre_hooks = None
    Runtime._system_post_hooks = None
    yield
    _stop_leaked_broker()  # close the thread broker before dropping the manager instance
    AKConfig._reset()
    ExecutionManager._reset()
    SandboxProviderFactory._reset()
    Runtime._system_pre_hooks = None
    Runtime._system_post_hooks = None


def _install_cfg(monkeypatch, sandbox_cfg):
    """Point AKConfig.get() at a stub carrying the sections the runtime hook chain reads."""

    class _Cfg:
        sandbox = sandbox_cfg
        multimodal = None
        guardrail = _GuardrailConfig()

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))


def _sandbox_cfg(flavor="thread", profiles=None, **overrides):
    if profiles is None:
        profiles = {"default": _SandboxProfileConfig(type=FAKE_DOTTED, scope="per_session")}
    return _SandboxConfig(enabled=True, broker=_ExecutionBrokerConfig(flavor=flavor), profiles=profiles, **overrides)


def _release_gate():
    """A threading.Event plus an async execute_code override that blocks on it (polled on
    the broker loop, so the caller can release it from the test loop/thread)."""
    release = threading.Event()

    async def blocked(self, code, language="python", timeout=None):
        while not release.is_set():
            await asyncio.sleep(0.005)
        return SandboxResult(stdout="late result", exit_code=0)

    return release, blocked


async def _wait_for_status(mgr, task_id, status, timeout=5.0):
    """Poll task_status until the task reaches ``status`` (fail the test on timeout)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = await mgr.task_status(task_id)
        if task is not None and task.status == status:
            return task
        await asyncio.sleep(0.02)
    pytest.fail(f"task {task_id} did not reach status '{status}' within {timeout}s")


# --------------------------------------------------------------------------- #
# End-to-end, both in-process flavors
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.parametrize("flavor", ["embedded", "thread"])
async def test_flavor_end_to_end(monkeypatch, flavor):
    _install_cfg(monkeypatch, _sandbox_cfg(flavor=flavor))
    mgr = ExecutionManager.get()
    session = InMemorySessionStore().new("ak-1")
    async with session:
        result = await mgr.execute(code="print('hi')")
        again = await mgr.execute(code="print('again')")
    assert result.exit_code == 0 and result.stdout == "print('hi')"
    assert result.sandbox_session_id == again.sandbox_session_id == "default:default"
    provider = SandboxProviderFactory.get("default")
    assert len(provider.created_ids) == 1  # session reused across calls


@pytest.mark.asyncio
async def test_thread_flavor_machinery_error_raises_while_waiting(monkeypatch):
    profile = _SandboxProfileConfig(type=FAKE_DOTTED, policy=_SandboxPolicyConfig(network_egress="deny", strict=True))
    _install_cfg(monkeypatch, _sandbox_cfg(flavor="thread", profiles={"default": profile}))
    mgr = ExecutionManager.get()
    session = InMemorySessionStore().new("ak-1")
    async with session:
        with pytest.raises(SandboxPolicyError):
            await mgr.execute(code="print(1)")


@pytest.mark.asyncio
async def test_thread_flavor_runs_provider_on_broker_loop(monkeypatch):
    """Concurrency contract: provider handles are only ever touched on the broker thread's loop."""
    _install_cfg(monkeypatch, _sandbox_cfg(flavor="thread"))
    seen = []
    original = FakeSandbox.execute_code

    async def capture(self, code, language="python", timeout=None):
        seen.append((asyncio.get_running_loop(), threading.current_thread()))
        return await original(self, code, language, timeout)

    monkeypatch.setattr(FakeSandbox, "execute_code", capture)
    mgr = ExecutionManager.get()
    session = InMemorySessionStore().new("ak-1")
    async with session:
        result = await mgr.execute(code="print(1)")
    assert result.exit_code == 0
    loop, thread = seen[0]
    assert loop is not asyncio.get_running_loop()
    assert thread is not threading.current_thread()
    assert thread.name == "ak-sandbox-broker"


# --------------------------------------------------------------------------- #
# Wait-policy promotion + late-completion recovery
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_promotion_and_late_completion_recovery(monkeypatch):
    _install_cfg(monkeypatch, _sandbox_cfg(flavor="thread"))
    release, blocked = _release_gate()
    monkeypatch.setattr(FakeSandbox, "execute_code", blocked)
    mgr = ExecutionManager.get()
    session = InMemorySessionStore().new("ak-1")
    async with session:
        outcome = await mgr.execute(code="slow", wait=0.05)
        assert isinstance(outcome, SandboxTask)
        assert outcome.status == "pending"

        # The promoted task is recorded in the AK session's registry.
        pending = await mgr.task_status(outcome.task_id)
        assert pending is not None and pending.status == "pending"

        # The execution finishes later; the completion lands via broker.result() and the
        # refreshed status is persisted back into the registry.
        release.set()
        await _wait_for_status(mgr, outcome.task_id, "succeeded")
        registry = session.get_non_volatile_cache().get("sandbox")
        assert registry["tasks"][outcome.task_id]["status"] == "succeeded"

        # The agent-facing check path resolves it too.
        payload = json.loads(await check_sandbox_task(outcome.task_id))
        assert payload["status"] == "succeeded"
        assert payload["sandbox_session_id"] == outcome.sandbox_session_id


@pytest.mark.asyncio
async def test_wait_zero_always_promotes(monkeypatch):
    _install_cfg(monkeypatch, _sandbox_cfg(flavor="thread"))
    release, blocked = _release_gate()
    monkeypatch.setattr(FakeSandbox, "execute_code", blocked)
    mgr = ExecutionManager.get()
    session = InMemorySessionStore().new("ak-1")
    async with session:
        outcome = await mgr.execute(code="slow", wait=0)
        assert isinstance(outcome, SandboxTask)
        release.set()
        await _wait_for_status(mgr, outcome.task_id, "succeeded")


@pytest.mark.asyncio
async def test_promoted_failure_becomes_failed_completion(monkeypatch):
    _install_cfg(monkeypatch, _sandbox_cfg(flavor="thread"))
    release = threading.Event()

    async def blocked_failure(self, code, language="python", timeout=None):
        while not release.is_set():
            await asyncio.sleep(0.005)
        raise RuntimeError("backend blew up")

    monkeypatch.setattr(FakeSandbox, "execute_code", blocked_failure)
    mgr = ExecutionManager.get()
    session = InMemorySessionStore().new("ak-1")
    async with session:
        outcome = await mgr.execute(code="slow", wait=0.05)
        assert isinstance(outcome, SandboxTask)
        release.set()
        # Inspect the broker's completion before task_status consumes it, then confirm the
        # promotion resolved to a terminal 'failed' task in the registry.
        completion = None
        for _ in range(250):
            completion = await mgr._broker.result(outcome.task_id)
            if completion is not None:
                break
            await asyncio.sleep(0.02)
        assert completion is not None and completion.status == "failed"
        assert "backend blew up" in completion.error
        task = await _wait_for_status(mgr, outcome.task_id, "failed")
        assert task.consumed is False


@pytest.mark.asyncio
async def test_thread_broker_close_is_idempotent(monkeypatch):
    _install_cfg(monkeypatch, _sandbox_cfg(flavor="thread"))
    mgr = ExecutionManager.get()
    session = InMemorySessionStore().new("ak-1")
    async with session:
        await mgr.execute(code="print(1)")
    broker = mgr._broker
    assert isinstance(broker, ThreadBroker)
    await broker.close()
    await broker.close()  # second close must not raise
    assert not broker._thread.is_alive()


# --------------------------------------------------------------------------- #
# Suspend/resume completion ingestion through Runtime.run
# --------------------------------------------------------------------------- #


class DummyRunner(Runner):
    async def run(self, agent, session, requests):
        prompt = requests[0].prompt if isinstance(requests[0], AgentRequestText) else ""
        return AgentReplyText(response=f"ok:{prompt}")

    async def stream(self, agent, session, requests):
        raise NotImplementedError()
        yield


class DummyAgent(Agent):
    def __init__(self, name):
        super().__init__(name, DummyRunner("DummyRunner"))
        self._name = name

    @property
    def name(self):
        return self._name

    @property
    def runner(self):
        return self._runner

    def get_a2a_card(self):
        pass

    def get_description(self):
        pass

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


def _completion(task_id, sandbox_session_id="default:default", stdout="late stdout"):
    return ExecutionCompletion(
        task_id=task_id,
        status="succeeded",
        result=SandboxResult(stdout=stdout, exit_code=0, sandbox_session_id=sandbox_session_id),
        sandbox_session=SandboxSession(
            sandbox_session_id=sandbox_session_id, profile="default", provider_type=FAKE_DOTTED, sandbox_id="sb-1", created_at=1.0, last_used_at=2.0
        ),
    )


def _seed_task(session, task_id):
    task = SandboxTask(task_id=task_id, sandbox_session_id="default:default", profile="default", submitted_at=0.0)
    session.get_non_volatile_cache().set("sandbox", {"sessions": {}, "tasks": {task_id: task.model_dump()}})


@pytest.mark.asyncio
async def test_runtime_ingests_completion_then_dedupes(monkeypatch):
    """The suspend/resume path: a completion request through Runtime.run injects the summary
    into the agent's turn; re-delivery and unknown task ids halt with the duplicate reply."""
    _install_cfg(monkeypatch, _sandbox_cfg(flavor="thread"))
    store = InMemorySessionStore()
    runtime = Runtime(store)
    agent = DummyAgent("dummy")
    session = store.new("ak-1")
    _seed_task(session, "t-1")
    completion = _completion("t-1").model_dump()

    reply = await runtime.run(agent, session, [AgentRequestText(prompt="hi"), AgentRequestAny(name="sandbox_task_completion", content=completion)])
    assert reply.response.startswith("ok:hi")
    assert "Sandbox task" in reply.response and "succeeded" in reply.response and "late stdout" in reply.response

    duplicate = await runtime.run(
        agent, session, [AgentRequestText(prompt="again"), AgentRequestAny(name="sandbox_task_completion", content=completion)]
    )
    assert "Duplicate or unknown" in duplicate.response

    unknown = await runtime.run(agent, session, [AgentRequestAny(name="sandbox_task_completion", content=_completion("t-404").model_dump())])
    assert "Duplicate or unknown" in unknown.response


# --------------------------------------------------------------------------- #
# Promoted-task tool JSON + broker flavor resolution
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_run_code_tool_returns_pending_task_json(monkeypatch):
    """The run_code tool's promoted-task branch: a wait-expiry promotion returns the
    {task_id, status: pending, sandbox_session_id} JSON contract."""
    _install_cfg(monkeypatch, _sandbox_cfg(flavor="thread"))
    release, blocked = _release_gate()
    monkeypatch.setattr(FakeSandbox, "execute_code", blocked)
    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", AKConfig.get)  # keep stub
    session = InMemorySessionStore().new("ak-1")
    async with session:
        # wait_timeout=0 → always promote
        cfg = AKConfig.get().sandbox
        cfg.broker.wait_timeout = 0
        payload = json.loads(await run_code("slow"))
        assert payload["status"] == "pending"
        assert payload["task_id"] and payload["sandbox_session_id"] == "default:default"
        release.set()


def test_broker_factory_unknown_flavor_raises_listing_builtins(monkeypatch):
    """An unknown non-dotted broker flavor fails loud with the #541 error shape."""
    _install_cfg(monkeypatch, _sandbox_cfg(flavor="sqs"))  # not landed until iteration 8
    with pytest.raises(SandboxConfigError) as exc_info:
        ExecutionBrokerFactory.get()
    assert "embedded" in str(exc_info.value) and "thread" in str(exc_info.value)
