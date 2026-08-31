"""Tests for the #503 sandbox queue broker: iteration 1 covers the wire codec, the additive
wire-contract fields, ``BrokerWorkerCore``'s ``error_type`` stamping, and the removal of the
never-read ``request_queue_url``/``object_store_bucket`` config fields."""

import json

import pytest

from agentkernel.core.config import AKConfig, _ExecutionBrokerConfig, _GuardrailConfig, _SandboxConfig, _SandboxProfileConfig
from agentkernel.core.runtime import Runtime
from agentkernel.sandbox.broker.base import ExecutionCompletion, ExecutionRequest
from agentkernel.sandbox.broker.wire import BrokerWireCodec
from agentkernel.sandbox.broker.worker import BrokerWorkerCore
from agentkernel.sandbox.errors import SandboxTimeoutError
from agentkernel.sandbox.factory import SandboxProviderFactory
from agentkernel.sandbox.manager import ExecutionManager
from agentkernel.sandbox.model import SandboxFile, SandboxPolicy, SandboxPrincipal, SandboxResult, SandboxSession
from agentkernel.sandbox.testing import FakeSandbox

FAKE_DOTTED = "agentkernel.sandbox.testing.FakeSandboxProvider"

BINARY = bytes([0, 255, 128, 10, 13, 200])  # not valid UTF-8; exercises the base64 wire rule


@pytest.fixture(autouse=True)
def reset_singletons():
    AKConfig._reset()
    ExecutionManager._reset()
    SandboxProviderFactory._reset()
    Runtime._system_pre_hooks = None
    Runtime._system_post_hooks = None
    yield
    AKConfig._reset()
    ExecutionManager._reset()
    SandboxProviderFactory._reset()
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
