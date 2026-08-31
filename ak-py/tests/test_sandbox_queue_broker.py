"""Tests for the #503 sandbox queue broker. Iteration 1 covers the wire codec, the additive
wire-contract field, ``BrokerWorkerCore``'s ``error_type`` stamping, and the removal of the
never-read ``request_queue_url``/``object_store_bucket`` config fields; iteration 2 covers
the ``queue`` broker flavor client (``QueueExecutionBroker``) over the ``in_memory``
transport and response store, faking the worker by writing completion records into the store."""

import json
import time

import pytest

from agentkernel.core.config import (
    AKConfig,
    _ExecutionBrokerConfig,
    _GuardrailConfig,
    _QueuesConfig,
    _ResponseStoreConfig,
    _SandboxConfig,
    _SandboxProfileConfig,
)
from agentkernel.core.runtime import Runtime
from agentkernel.pipeline.envelope import ATTR_REQUEST_ID, QueueName
from agentkernel.pipeline.response_store.in_memory import InMemoryResponseStore
from agentkernel.pipeline.transport.in_memory import InMemoryTransport
from agentkernel.sandbox.broker.base import ExecutionCompletion, ExecutionRequest
from agentkernel.sandbox.broker.queue import QueueExecutionBroker
from agentkernel.sandbox.broker.wire import BrokerWireCodec
from agentkernel.sandbox.broker.worker import BrokerWorkerCore
from agentkernel.sandbox.errors import ExecutionBrokerError, SandboxConfigError, SandboxPolicyError, SandboxTimeoutError
from agentkernel.sandbox.factory import ExecutionBrokerFactory, SandboxProviderFactory
from agentkernel.sandbox.manager import ExecutionManager
from agentkernel.sandbox.model import SandboxFile, SandboxPolicy, SandboxPrincipal, SandboxResult, SandboxSession, SandboxTask
from agentkernel.sandbox.testing import FakeSandbox

FAKE_DOTTED = "agentkernel.sandbox.testing.FakeSandboxProvider"

BINARY = bytes([0, 255, 128, 10, 13, 200])  # not valid UTF-8; exercises the base64 wire rule


@pytest.fixture(autouse=True)
def reset_singletons():
    AKConfig._reset()
    ExecutionManager._reset()
    SandboxProviderFactory._reset()
    InMemoryTransport.reset()
    InMemoryResponseStore.reset()
    Runtime._system_pre_hooks = None
    Runtime._system_post_hooks = None
    yield
    AKConfig._reset()
    ExecutionManager._reset()
    SandboxProviderFactory._reset()
    InMemoryTransport.reset()
    InMemoryResponseStore.reset()
    Runtime._system_pre_hooks = None
    Runtime._system_post_hooks = None


def _install_cfg(monkeypatch, sandbox_cfg):
    class _Cfg:
        sandbox = sandbox_cfg
        multimodal = None
        guardrail = _GuardrailConfig()

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))


def _sandbox_cfg(profiles=None, **overrides):
    profiles = profiles or {"default": _SandboxProfileConfig(type=FAKE_DOTTED)}
    return _SandboxConfig(enabled=True, broker=_ExecutionBrokerConfig(flavor="embedded"), profiles=profiles, **overrides)


def _session(sandbox_session_id="default:default", profile="default"):
    return SandboxSession(sandbox_session_id=sandbox_session_id, profile=profile, provider_type=FAKE_DOTTED, created_at=1.0, last_used_at=1.0)


def _request(operation="execute_code", payload=None, profile="default", **overrides):
    kwargs = dict(
        task_id="t-1",
        operation=operation,
        payload=payload if payload is not None else {"code": "print('hi')"},
        profile=profile,
        principal=SandboxPrincipal(subject="agent"),
        policy=SandboxPolicy(),
        sandbox_session=_session(profile=profile),
        ak_session_id="ak-1",
        agent="agent",
    )
    kwargs.update(overrides)
    return ExecutionRequest(**kwargs)


class TestWireCodec:
    def test_upload_payload_binary_round_trip(self):
        request = _request(operation="upload_file", payload={"path": "data.bin", "content": BINARY})
        body = BrokerWireCodec.encode_request(request)
        json.loads(body)  # the wire form is plain JSON
        decoded = BrokerWireCodec.decode_request(body)
        assert decoded.payload["content"] == BINARY
        assert decoded.payload["path"] == "data.bin"
        # Encoding never mutates the caller's request object.
        assert request.payload["content"] == BINARY

    def test_non_upload_payload_passes_through(self):
        request = _request(payload={"code": "print(1)", "language": "python"})
        decoded = BrokerWireCodec.decode_request(BrokerWireCodec.encode_request(request))
        assert decoded.payload == {"code": "print(1)", "language": "python"}
        assert decoded.task_id == request.task_id
        assert decoded.wait_deadline is None

    def test_wait_deadline_round_trip(self):
        request = _request(wait_deadline=123.0)
        decoded = BrokerWireCodec.decode_request(BrokerWireCodec.encode_request(request))
        assert decoded.wait_deadline == 123.0

    def test_completion_output_files_binary_round_trip(self):
        completion = ExecutionCompletion(
            task_id="t-1",
            status="succeeded",
            result=SandboxResult(stdout="ok", output_files=[SandboxFile(path="out.bin", content=BINARY)]),
            sandbox_session=_session(),
        )
        data = BrokerWireCodec.encode_completion(completion)
        json.dumps(data)  # the stored form is JSON-safe
        decoded = BrokerWireCodec.decode_completion(data)
        assert decoded.result.output_files[0].content == BINARY
        # decode_completion accepts the JSON-string form too (the response-store record body).
        assert BrokerWireCodec.decode_completion(json.dumps(data)).result.output_files[0].content == BINARY

    def test_sandbox_file_python_mode_keeps_bytes(self):
        file = SandboxFile(path="x", content=BINARY)
        assert file.model_dump()["content"] == BINARY  # nv_cache / in-process form unchanged
        assert SandboxFile(**file.model_dump()).content == BINARY

    def test_sandbox_file_rejects_non_base64_wire_strings(self):
        with pytest.raises(Exception):
            SandboxFile(path="x", content="not base64!!")


class TestErrorTypeStamping:
    @pytest.mark.asyncio
    async def test_failed_completion_carries_error_type(self, monkeypatch):
        _install_cfg(monkeypatch, _sandbox_cfg())
        completion = await BrokerWorkerCore().process(_request(profile="missing"))
        assert completion.status == "failed"
        assert completion.error_type == "SandboxConfigError"
        assert "missing" in completion.error

    @pytest.mark.asyncio
    async def test_timed_out_completion_carries_error_type(self, monkeypatch):
        _install_cfg(monkeypatch, _sandbox_cfg())

        async def raise_timeout(self, code, language="python", timeout=None):
            raise SandboxTimeoutError("too slow")

        monkeypatch.setattr(FakeSandbox, "execute_code", raise_timeout)
        completion = await BrokerWorkerCore().process(_request())
        assert completion.status == "timed_out"
        assert completion.error_type == "SandboxTimeoutError"

    @pytest.mark.asyncio
    async def test_success_leaves_error_type_unset(self, monkeypatch):
        _install_cfg(monkeypatch, _sandbox_cfg())
        completion = await BrokerWorkerCore().process(_request())
        assert completion.status == "succeeded"
        assert completion.error_type is None


class TestRemovedBrokerConfigFields:
    def test_stale_yaml_keys_are_ignored(self):
        broker = _ExecutionBrokerConfig.model_validate(
            {"flavor": "thread", "request_queue_url": "https://sqs.example/queue", "object_store_bucket": "bucket"}
        )
        assert not hasattr(broker, "request_queue_url")
        assert not hasattr(broker, "object_store_bucket")
        assert broker.flavor == "thread"

    def test_stale_env_vars_are_ignored(self, monkeypatch):
        monkeypatch.setenv("AK_SANDBOX__BROKER__REQUEST_QUEUE_URL", "https://sqs.example/queue")
        monkeypatch.setenv("AK_SANDBOX__BROKER__OBJECT_STORE_BUCKET", "bucket")
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        AKConfig._reset()
        config = AKConfig.get()
        assert not hasattr(config.sandbox.broker, "request_queue_url")
        assert not hasattr(config.sandbox.broker, "object_store_bucket")

    def test_new_fields_have_expected_defaults(self):
        broker = _ExecutionBrokerConfig()
        assert broker.queue is None
        assert broker.wait_poll_interval == 0.5
        assert broker.wait_timeout == 60.0


def _queue_broker(**overrides):
    """A client over the permitted single-process pairing: in_memory transport + store."""
    kwargs = dict(
        flavor="queue",
        queue=_QueuesConfig(type="in_memory"),
        response_store=_ResponseStoreConfig(type="in_memory"),
        wait_poll_interval=0.01,
    )
    kwargs.update(overrides)
    return QueueExecutionBroker(_ExecutionBrokerConfig(**kwargs))


def _completion(status="succeeded", *, task_id="t-1", error=None, error_type=None, result=None):
    if status == "succeeded" and result is None:
        result = SandboxResult(stdout="done")
    return ExecutionCompletion(task_id=task_id, status=status, result=result, error=error, error_type=error_type, sandbox_session=_session())


def _store_completion(completion, status_code=200):
    """Fake the worker's output loop: put the ready-to-store record into the shared store."""
    InMemoryResponseStore().add_message(
        {
            "request_id": completion.task_id,
            "session_id": "ak-1",
            "status_code": status_code,
            "body": BrokerWireCodec.encode_completion(completion),
        }
    )


class TestQueueBrokerClient:
    def test_factory_resolves_queue_flavor(self, monkeypatch):
        broker_cfg = _ExecutionBrokerConfig(
            flavor="queue", queue=_QueuesConfig(type="in_memory"), response_store=_ResponseStoreConfig(type="in_memory")
        )
        cfg = _SandboxConfig(enabled=True, broker=broker_cfg, profiles={"default": _SandboxProfileConfig(type=FAKE_DOTTED)})
        _install_cfg(monkeypatch, cfg)
        assert isinstance(ExecutionBrokerFactory.get(), QueueExecutionBroker)

    def test_constructor_requires_the_queue_block(self):
        with pytest.raises(SandboxConfigError, match="sandbox.broker.queue"):
            QueueExecutionBroker(_ExecutionBrokerConfig(flavor="queue", response_store=_ResponseStoreConfig(type="in_memory")))

    def test_constructor_requires_the_response_store_block(self):
        with pytest.raises(SandboxConfigError, match="sandbox.broker.response_store"):
            QueueExecutionBroker(_ExecutionBrokerConfig(flavor="queue", queue=_QueuesConfig(type="in_memory")))

    @pytest.mark.asyncio
    async def test_wait_zero_promotes_and_sends_the_wire_shape(self):
        broker = _queue_broker()
        request = _request()
        task = await broker.submit(request, wait=0)
        assert isinstance(task, SandboxTask)
        assert task.status == "pending" and task.task_id == request.task_id
        assert task.sandbox_session_id == request.sandbox_session.sandbox_session_id
        consumer = InMemoryTransport().create_consumer(QueueName.INPUT)
        [message] = consumer.fetch(10, 0.05)
        assert message.attributes[ATTR_REQUEST_ID] == request.task_id
        assert message.group_id == request.sandbox_session.sandbox_session_id
        assert message.dedup_id == request.task_id
        decoded = BrokerWireCodec.decode_request(message.body)
        assert decoded.operation == request.operation and decoded.payload == request.payload

    @pytest.mark.asyncio
    async def test_completed_result_returned_within_wait(self):
        broker = _queue_broker()
        _store_completion(_completion())
        result = await broker.submit(_request(), wait=5)
        assert isinstance(result, SandboxResult) and result.stdout == "done"
        # The record is read without get_and_delete: the store stays the durable source of truth.
        assert (await broker.result("t-1")) is not None

    @pytest.mark.asyncio
    async def test_wait_none_is_bounded_by_wait_timeout(self):
        broker = _queue_broker(wait_timeout=0.05)
        start = time.monotonic()
        outcome = await broker.submit(_request(), wait=None)
        assert isinstance(outcome, SandboxTask) and outcome.status == "pending"
        assert time.monotonic() - start < 5  # bounded: never the in-process flavors' indefinite wait

    @pytest.mark.asyncio
    async def test_destroy_is_fire_and_forget_and_fifo_ordered(self):
        broker = _queue_broker(wait_timeout=60.0)
        await broker.submit(_request(), wait=0)
        start = time.monotonic()
        task = await broker.submit(_request(operation="destroy", payload={}, task_id="t-2"), wait=None)
        assert isinstance(task, SandboxTask) and time.monotonic() - start < 1.0  # no bounded poll for destroys
        # Per-group FIFO: one in flight per session, the destroy only after the prior op acks.
        consumer = InMemoryTransport().create_consumer(QueueName.INPUT)
        [first] = consumer.fetch(10, 0.05)
        assert BrokerWireCodec.decode_request(first.body).operation == "execute_code"
        consumer.ack(first)
        [second] = consumer.fetch(10, 0.05)
        assert BrokerWireCodec.decode_request(second.body).operation == "destroy"

    @pytest.mark.asyncio
    async def test_failed_completion_re_raises_the_typed_error(self):
        broker = _queue_broker()
        _store_completion(_completion("failed", error="policy says no", error_type="SandboxPolicyError"), status_code=500)
        with pytest.raises(SandboxPolicyError, match="policy says no"):
            await broker.submit(_request(), wait=5)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("error_type", [None, "ValueError", "NoSuchError"])
    async def test_unhonored_error_type_degrades_to_broker_error(self, error_type):
        # Only names defined in agentkernel.sandbox.errors are honored on the wire.
        broker = _queue_broker()
        _store_completion(_completion("failed", error="boom", error_type=error_type), status_code=500)
        with pytest.raises(ExecutionBrokerError, match="boom"):
            await broker.submit(_request(), wait=5)

    @pytest.mark.asyncio
    async def test_timed_out_completion_raises_sandbox_timeout(self):
        broker = _queue_broker()
        _store_completion(_completion("timed_out", error="too slow"), status_code=504)
        with pytest.raises(SandboxTimeoutError, match="too slow"):
            await broker.submit(_request(), wait=5)

    @pytest.mark.asyncio
    async def test_worker_timeout_ceiling_rejects_before_send(self):
        broker = _queue_broker(worker_timeout_ceiling=10.0)
        with pytest.raises(SandboxPolicyError) as exc_info:
            await broker.submit(_request(policy=SandboxPolicy(timeout=30.0)), wait=0)
        assert "30" in str(exc_info.value) and "10" in str(exc_info.value)
        consumer = InMemoryTransport().create_consumer(QueueName.INPUT)
        assert consumer.fetch(1, 0.01) == []  # nothing was sent

    @pytest.mark.asyncio
    async def test_oversized_request_rejected_at_submit(self):
        broker = _queue_broker(inline_payload_max_bytes=64)
        with pytest.raises(ExecutionBrokerError, match="execute_code"):
            await broker.submit(_request(payload={"code": "x" * 500}), wait=0)
        consumer = InMemoryTransport().create_consumer(QueueName.INPUT)
        assert consumer.fetch(1, 0.01) == []

    @pytest.mark.asyncio
    async def test_result_serves_the_store_from_any_process(self):
        broker = _queue_broker()
        assert await broker.result("missing") is None
        _store_completion(_completion())
        completion = await broker.result("t-1")
        assert completion is not None and completion.status == "succeeded"

    @pytest.mark.asyncio
    async def test_poll_survives_a_transient_store_read_failure(self, monkeypatch):
        broker = _queue_broker()
        calls = {"n": 0}
        real = InMemoryResponseStore.get_message

        def flaky(self, request_id, get_and_delete=False):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("store blip")
            return real(self, request_id, get_and_delete)

        monkeypatch.setattr(InMemoryResponseStore, "get_message", flaky)
        _store_completion(_completion())
        result = await broker.submit(_request(), wait=5)
        assert isinstance(result, SandboxResult) and calls["n"] >= 2
