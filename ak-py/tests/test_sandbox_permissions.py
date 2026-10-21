"""Tests for profile permissions (#692): ``SandboxPermissionGuard`` and its wiring into
``BrokerWorkerCore`` and ``ThreadBroker`` — one audit line per denial, the capability-mismatch
warning, the legacy ``install_packages`` shim, and the effective timeout with its backstop.
"""

import asyncio
import logging

import pytest

from agentkernel.core.config import (
    AKConfig,
    _ExecutionBrokerConfig,
    _GuardrailConfig,
    _SandboxConfig,
    _SandboxIdentityConfig,
    _SandboxProfileConfig,
)
from agentkernel.core.runtime import Runtime
from agentkernel.sandbox.broker.base import ExecutionRequest
from agentkernel.sandbox.broker.thread import ThreadBroker
from agentkernel.sandbox.broker.worker import BrokerWorkerCore
from agentkernel.sandbox.errors import SandboxCapabilityError, SandboxPermissionDeniedError, SandboxPolicyError
from agentkernel.sandbox.factory import SandboxProviderFactory
from agentkernel.sandbox.manager import ExecutionManager
from agentkernel.sandbox.model import PackageInstallPolicy, SandboxPolicy, SandboxPrincipal, SandboxResult, SandboxSession
from agentkernel.sandbox.permission import PermissionAuditContext, SandboxPermissionGuard
from agentkernel.sandbox.testing import FakeSandbox, FakeSandboxProvider

BROKER_LOGGER = "ak.sandbox.broker"
FAKE_DOTTED = "agentkernel.sandbox.testing.FakeSandboxProvider"


class _PkgSandbox(FakeSandbox):
    """A FakeSandbox with a modern install_packages that records each call."""

    calls: list[tuple[list[str], str, float | None]] = []

    async def install_packages(self, packages, ecosystem="python", timeout=None):
        type(self).calls.append((packages, ecosystem, timeout))
        return SandboxResult(stdout="installed", exit_code=0)


class _PkgProvider(FakeSandboxProvider):
    """A package-capable fake: declares the python ecosystem and hands out _PkgSandbox."""

    sandbox_cls: type[FakeSandbox] = _PkgSandbox
    capabilities = FakeSandboxProvider.capabilities.derive(package_ecosystems=["python"], package_install=True)

    async def create(self, *, principal, policy):
        sandbox = await super().create(principal=principal, policy=policy)
        replacement = self.sandbox_cls(sandbox.id, list(self.capabilities.languages))
        self._sandboxes[sandbox.id] = replacement
        return replacement


class _LegacySandbox(FakeSandbox):
    """A pre-#692 bring-your-own handle: the one-argument install_packages override."""

    calls: list[list[str]] = []

    async def install_packages(self, packages):
        type(self).calls.append(packages)
        return SandboxResult(stdout="legacy", exit_code=0)


class _LegacyProvider(_PkgProvider):
    sandbox_cls = _LegacySandbox


class _HangingSandbox(FakeSandbox):
    """Ignores its timeout, so only the worker's backstop can end the call."""

    async def install_packages(self, packages, ecosystem="python", timeout=None):
        await asyncio.sleep(30)
        return SandboxResult()


class _HangingProvider(_PkgProvider):
    sandbox_cls = _HangingSandbox


PKG_DOTTED = f"{__name__}._PkgProvider"
LEGACY_DOTTED = f"{__name__}._LegacyProvider"
HANGING_DOTTED = f"{__name__}._HangingProvider"

INSTALL_ALL = PackageInstallPolicy(ecosystems=["python", "node"])


@pytest.fixture(autouse=True)
def reset_singletons():
    AKConfig._reset()
    ExecutionManager._reset()
    SandboxProviderFactory._reset()
    Runtime._system_pre_hooks = None
    Runtime._system_post_hooks = None
    _PkgSandbox.calls = []
    _LegacySandbox.calls = []
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


def _use_provider(monkeypatch, dotted=PKG_DOTTED, **profile_overrides):
    profile = _SandboxProfileConfig(type=dotted, **profile_overrides)
    _install_cfg(monkeypatch, _SandboxConfig(enabled=True, broker=_ExecutionBrokerConfig(flavor="embedded"), profiles={"default": profile}))


def _request(operation="execute_code", payload=None, policy=None, **overrides):
    kwargs = dict(
        task_id="t-1",
        operation=operation,
        payload=payload if payload is not None else {"code": "print('hi')"},
        profile="default",
        principal=SandboxPrincipal(subject="agent"),
        policy=policy if policy is not None else SandboxPolicy(),
        sandbox_session=SandboxSession(sandbox_session_id="sess-1", profile="default", provider_type=PKG_DOTTED, created_at=1.0, last_used_at=1.0),
        ak_session_id="ak-1",
        agent="agent-a",
    )
    kwargs.update(overrides)
    return ExecutionRequest(**kwargs)


def _install(packages=None, ecosystem="python", policy=None):
    return _request("install_packages", {"packages": packages or ["requests"], "ecosystem": ecosystem}, policy=policy)


def _broker_records(caplog):
    return [r for r in caplog.records if r.name == BROKER_LOGGER]


def _denials(caplog):
    return [r for r in _broker_records(caplog) if r.getMessage().startswith("Sandbox permission denied")]


# --------------------------------------------------------------------------- #
# SandboxPermissionGuard
# --------------------------------------------------------------------------- #


_CONTEXT = PermissionAuditContext(profile="prof-a", agent="agent-a", ak_session_id="ak-1", sandbox_session_id="sess-1")


@pytest.mark.parametrize(
    "operation, payload, policy",
    [
        ("execute_code", {"code": "zzq_secret_code()", "language": "bash"}, SandboxPolicy(languages=["python"])),
        ("execute_code", {"code": "zzq_secret_code()"}, SandboxPolicy(languages=[])),
        ("install_packages", {"packages": ["zzq-secret-pkg"]}, SandboxPolicy()),
        ("install_packages", {"packages": ["zzq-secret-pkg"], "ecosystem": "node"}, SandboxPolicy(package_install=PackageInstallPolicy())),
    ],
    ids=["language-not-listed", "command-only-profile", "installs-not-permitted", "ecosystem-not-listed"],
)
def test_guard_denies_and_logs_once(caplog, operation, payload, policy):
    with caplog.at_level("WARNING", logger=BROKER_LOGGER):
        with pytest.raises(SandboxPermissionDeniedError) as excinfo:
            SandboxPermissionGuard().check_operation(operation, payload, policy, _CONTEXT)
    records = _broker_records(caplog)
    assert len(records) == 1
    line = records[0].getMessage()
    assert records[0].levelno == logging.WARNING
    for field in (f"operation={operation}", "profile=prof-a", "agent=agent-a", "ak_session_id=ak-1", "sandbox_session_id=sess-1"):
        assert field in line
    # No code or package text reaches the log or the error.
    assert "zzq" not in line and "zzq" not in str(excinfo.value)
    assert str(excinfo.value).startswith(f"profile 'prof-a' does not permit {operation}: ")
    assert str(excinfo.value).endswith("this is a configuration decision, so do not retry it through run_command")


@pytest.mark.parametrize(
    "operation, payload, policy",
    [
        ("execute_code", {"code": "x"}, SandboxPolicy()),  # languages None = provider-declared
        ("execute_code", {"code": "x", "language": "bash"}, SandboxPolicy(languages=["python", "bash"])),
        ("execute_code", {"code": "x"}, SandboxPolicy(languages=["python"])),  # language defaults to python
        ("install_packages", {"packages": ["requests"]}, SandboxPolicy(package_install=PackageInstallPolicy())),
        ("install_packages", {"packages": ["lodash"], "ecosystem": "node"}, SandboxPolicy(package_install=INSTALL_ALL)),
        # Never gated, even under the most restrictive policy.
        ("execute_command", {"command": "ls"}, SandboxPolicy(languages=[])),
        ("upload_file", {"path": "p", "content": b""}, SandboxPolicy(languages=[])),
        ("download_file", {"path": "p"}, SandboxPolicy(languages=[])),
        ("destroy", {}, SandboxPolicy(languages=[])),
    ],
)
def test_guard_permits(caplog, operation, payload, policy):
    with caplog.at_level("WARNING", logger=BROKER_LOGGER):
        SandboxPermissionGuard().check_operation(operation, payload, policy, _CONTEXT)
    assert _broker_records(caplog) == []


def test_guard_check_reads_the_request():
    with pytest.raises(SandboxPermissionDeniedError, match="profile 'default'"):
        SandboxPermissionGuard().check(_install())


# --------------------------------------------------------------------------- #
# BrokerWorkerCore wiring
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_process_raw_install_is_denied_with_one_record(monkeypatch, caplog):
    # Behavioural change 1: a request whose policy carries no package_install is denied.
    _use_provider(monkeypatch)
    with caplog.at_level("WARNING", logger=BROKER_LOGGER):
        completion = await BrokerWorkerCore().process(_install(["zzq-pkg"]))
    assert completion.status == "failed"
    assert completion.error_type == "SandboxPermissionDeniedError"
    assert len(_broker_records(caplog)) == 1  # the guard's line; process() adds no generic warning
    assert len(_denials(caplog)) == 1


@pytest.mark.asyncio
async def test_denial_happens_before_acquire(monkeypatch):
    _use_provider(monkeypatch)
    worker = BrokerWorkerCore()
    provider = SandboxProviderFactory.get("default")
    with pytest.raises(SandboxPermissionDeniedError):
        await worker.run(_request(payload={"code": "x", "language": "bash"}, policy=SandboxPolicy(languages=["python"])))
    assert provider.created_ids == []
    # A permitted request on the same worker does create, so the check above watched the provider in use.
    await worker.run(_request(policy=SandboxPolicy(languages=["python"])))
    assert len(provider.created_ids) == 1


@pytest.mark.asyncio
async def test_thread_broker_denial_logs_once(monkeypatch, caplog):
    _use_provider(monkeypatch)
    broker = ThreadBroker()
    try:
        with caplog.at_level("WARNING", logger=BROKER_LOGGER):
            with pytest.raises(SandboxPermissionDeniedError):
                await broker.submit(_install())
        assert len(_broker_records(caplog)) == 1
        completion = await broker.result("t-1")
        assert completion is not None and completion.status == "failed"
    finally:
        await broker.close()


@pytest.mark.asyncio
async def test_thread_broker_other_policy_failures_keep_the_generic_warning(monkeypatch, caplog):
    _use_provider(monkeypatch)
    broker = ThreadBroker()
    try:
        with caplog.at_level("WARNING", logger=BROKER_LOGGER):
            with pytest.raises(SandboxPolicyError) as excinfo:
                await broker.submit(_request(policy=SandboxPolicy(network_egress="deny")))
        assert not isinstance(excinfo.value, SandboxPermissionDeniedError)
        assert any("failed" in r.getMessage() for r in _broker_records(caplog))
    finally:
        await broker.close()


@pytest.mark.asyncio
async def test_check_principal_failure_keeps_the_generic_warning(monkeypatch, caplog):
    # A user-identity profile on a provider that does not declare principal_user.
    _use_provider(monkeypatch, identity=_SandboxIdentityConfig(mode="user"))
    with caplog.at_level("WARNING", logger=BROKER_LOGGER):
        completion = await BrokerWorkerCore().process(_request())
    assert completion.status == "failed"
    assert any("failed" in r.getMessage() for r in _broker_records(caplog))


@pytest.mark.asyncio
async def test_enforce_policy_failure_keeps_the_generic_warning(monkeypatch, caplog):
    # An unenforceable dimension under strict.
    _use_provider(monkeypatch)
    with caplog.at_level("WARNING", logger=BROKER_LOGGER):
        completion = await BrokerWorkerCore().process(_request(policy=SandboxPolicy(network_egress="deny")))
    assert completion.error_type == "SandboxPolicyError"
    assert any("failed" in r.getMessage() for r in _broker_records(caplog))


@pytest.mark.asyncio
async def test_permitted_install_reaches_the_handle(monkeypatch):
    _use_provider(monkeypatch)
    result, _ = await BrokerWorkerCore().run(_install(["requests"], policy=SandboxPolicy(package_install=PackageInstallPolicy())))
    assert result.stdout == "installed"
    assert _PkgSandbox.calls == [(["requests"], "python", 120.0)]


# --------------------------------------------------------------------------- #
# Capability-mismatch warning
# --------------------------------------------------------------------------- #


def _mismatch_records(caplog):
    return [r for r in _broker_records(caplog) if "does not declare it" in r.getMessage()]


@pytest.mark.asyncio
async def test_mismatch_warning_once_per_provider_profile(monkeypatch, caplog):
    _use_provider(monkeypatch)  # declares python only, languages python + bash
    worker = BrokerWorkerCore()
    policy = SandboxPolicy(package_install=INSTALL_ALL, languages=["python", "ruby"])
    with caplog.at_level("WARNING", logger=BROKER_LOGGER):
        await worker.process(_request(policy=policy))
        await worker.process(_request(policy=policy))
    records = _mismatch_records(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    assert "package ecosystem 'node'" in message and "language 'ruby'" in message
    assert "'python'" not in message  # declared, so not listed


@pytest.mark.asyncio
async def test_mismatch_warning_for_a_non_installing_provider(monkeypatch, caplog):
    _use_provider(monkeypatch, dotted=FAKE_DOTTED)  # package_install=False
    with caplog.at_level("WARNING", logger=BROKER_LOGGER):
        completion = await BrokerWorkerCore().process(_install(policy=SandboxPolicy(package_install=PackageInstallPolicy())))
    assert completion.error_type == "SandboxCapabilityError"  # permitted, but the provider cannot
    assert len(_mismatch_records(caplog)) == 1


@pytest.mark.asyncio
async def test_mismatch_and_non_strict_policy_warnings_are_independent(monkeypatch, caplog):
    _use_provider(monkeypatch)
    policy = SandboxPolicy(network_egress="deny", strict=False, package_install=INSTALL_ALL)
    with caplog.at_level("WARNING", logger=BROKER_LOGGER):
        await BrokerWorkerCore().process(_request(policy=policy))
    assert len(_mismatch_records(caplog)) == 1
    assert len([r for r in _broker_records(caplog) if "cannot enforce policy dimensions" in r.getMessage()]) == 1


@pytest.mark.asyncio
async def test_no_mismatch_warning_when_declared(monkeypatch, caplog):
    _use_provider(monkeypatch)
    with caplog.at_level("WARNING", logger=BROKER_LOGGER):
        await BrokerWorkerCore().process(_request(policy=SandboxPolicy(package_install=PackageInstallPolicy(), languages=["bash"])))
    assert _mismatch_records(caplog) == []


# --------------------------------------------------------------------------- #
# Legacy install_packages shim
# --------------------------------------------------------------------------- #


def _deprecations(caplog):
    return [r for r in _broker_records(caplog) if "deprecated" in r.getMessage()]


@pytest.mark.asyncio
async def test_legacy_override_runs_python_with_one_deprecation_warning(monkeypatch, caplog):
    _use_provider(monkeypatch, dotted=LEGACY_DOTTED)
    worker = BrokerWorkerCore()
    policy = SandboxPolicy(package_install=PackageInstallPolicy())
    with caplog.at_level("WARNING", logger=BROKER_LOGGER):
        r1, _ = await worker.run(_install(["requests"], policy=policy))
        r2, _ = await worker.run(_install(["numpy"], policy=policy))
    assert r1.stdout == r2.stdout == "legacy"
    assert _LegacySandbox.calls == [["requests"], ["numpy"]]
    records = _deprecations(caplog)
    assert len(records) == 1 and "_LegacySandbox" in records[0].getMessage()


@pytest.mark.asyncio
async def test_legacy_override_rejects_non_python_ecosystem(monkeypatch):
    _use_provider(monkeypatch, dotted=LEGACY_DOTTED)
    with pytest.raises(SandboxCapabilityError, match="package_ecosystem:node"):
        await BrokerWorkerCore().run(_install(["lodash"], "node", policy=SandboxPolicy(package_install=INSTALL_ALL)))
    assert _LegacySandbox.calls == []


@pytest.mark.asyncio
async def test_modern_override_logs_no_deprecation(monkeypatch, caplog):
    _use_provider(monkeypatch)
    with caplog.at_level("WARNING", logger=BROKER_LOGGER):
        await BrokerWorkerCore().run(_install(["lodash"], "node", policy=SandboxPolicy(package_install=INSTALL_ALL)))
    assert _PkgSandbox.calls == [(["lodash"], "node", 120.0)]
    assert _deprecations(caplog) == []


# --------------------------------------------------------------------------- #
# Effective timeout and backstop
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_install_uses_its_own_timeout_when_set(monkeypatch):
    _use_provider(monkeypatch)
    worker = BrokerWorkerCore()
    await worker.run(_install(policy=SandboxPolicy(timeout=30, package_install=PackageInstallPolicy(timeout=600))))
    await worker.run(_install(policy=SandboxPolicy(timeout=30, package_install=PackageInstallPolicy())))
    assert [timeout for _, _, timeout in _PkgSandbox.calls] == [600, 30]


@pytest.mark.asyncio
async def test_execute_code_uses_policy_timeout(monkeypatch):
    _use_provider(monkeypatch)
    seen = []

    async def record(self, code, language="python", timeout=None):
        seen.append(timeout)
        return SandboxResult()

    monkeypatch.setattr(_PkgSandbox, "execute_code", record)
    await BrokerWorkerCore().run(_request(policy=SandboxPolicy(timeout=30, package_install=PackageInstallPolicy(timeout=600))))
    assert seen == [30]


@pytest.mark.asyncio
async def test_backstop_fires_after_the_grace(monkeypatch):
    _use_provider(monkeypatch, dotted=HANGING_DOTTED)
    monkeypatch.setattr("agentkernel.sandbox.broker.worker.BrokerWorkerCore.BACKSTOP_GRACE_SECONDS", 0.05)
    policy = SandboxPolicy(timeout=30, package_install=PackageInstallPolicy(timeout=0.05))
    completion = await asyncio.wait_for(BrokerWorkerCore().process(_install(policy=policy)), timeout=5)
    assert completion.status == "timed_out"
    assert "(backstop)" in completion.error and "0.05s" in completion.error
