"""Tests for profile permissions (#692): ``SandboxPermissionGuard`` and its wiring into
``BrokerWorkerCore`` and ``ThreadBroker`` — one audit line per denial, the capability-mismatch
warning, the legacy ``install_packages`` shim, and the effective timeout with its backstop —
plus the agent side: ``ExecutionManager``'s pre-submit checks and config warnings, the
``install_packages`` tool, and installs end to end over the embedded, thread and queue flavors.
"""

import asyncio
import json
import logging
import threading
import time

import pytest

from agentkernel.core.config import (
    AKConfig,
    _ExecutionBrokerConfig,
    _GuardrailConfig,
    _QueuesConfig,
    _ResponseStoreConfig,
    _SandboxConfig,
    _SandboxDockerConfig,
    _SandboxIdentityConfig,
    _SandboxPackageInstallConfig,
    _SandboxPolicyConfig,
    _SandboxProfileConfig,
)
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.pipeline.response_store.in_memory import InMemoryResponseStore
from agentkernel.pipeline.thread_runner import ThreadRunner
from agentkernel.pipeline.transport.in_memory import InMemoryTransport
from agentkernel.sandbox.broker.base import ExecutionRequest
from agentkernel.sandbox.broker.queue_worker import QueueBrokerWorker
from agentkernel.sandbox.broker.thread import ThreadBroker
from agentkernel.sandbox.broker.worker import BrokerWorkerCore
from agentkernel.sandbox.errors import SandboxCapabilityError, SandboxPermissionDeniedError, SandboxPolicyError
from agentkernel.sandbox.factory import SandboxProviderFactory
from agentkernel.sandbox.manager import ExecutionManager
from agentkernel.sandbox.model import PackageInstallPolicy, SandboxPolicy, SandboxPrincipal, SandboxResult, SandboxSession
from agentkernel.sandbox.permission import PermissionAuditContext, SandboxPermissionGuard
from agentkernel.sandbox.testing import FakeSandbox, FakeSandboxProvider, SandboxProviderContract
from agentkernel.sandbox.tools import install_packages as install_packages_tool
from agentkernel.sandbox.tools import run_code as run_code_tool

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


class _EcosystemOnlySandbox(FakeSandbox):
    """A pre-#692 bring-your-own handle that took an ecosystem but no timeout."""

    calls: list[tuple[list[str], str]] = []

    async def install_packages(self, packages, ecosystem="python"):
        if ecosystem not in ("python", "node"):
            raise SandboxCapabilityError(self.__class__.__name__, f"package_ecosystem:{ecosystem}")
        type(self).calls.append((packages, ecosystem))
        return SandboxResult(stdout="ecosystem-only", exit_code=0)


class _EcosystemOnlyProvider(_PkgProvider):
    sandbox_cls = _EcosystemOnlySandbox
    capabilities = FakeSandboxProvider.capabilities.derive(package_ecosystems=["python", "node"])


class _TimeoutOnlySandbox(FakeSandbox):
    async def install_packages(self, packages, timeout=None):
        return SandboxResult()


class _KwargsSandbox(FakeSandbox):
    async def install_packages(self, packages, **kwargs):
        return SandboxResult()


class _HangingSandbox(FakeSandbox):
    """Ignores its timeout, so only the worker's backstop can end the call."""

    async def install_packages(self, packages, ecosystem="python", timeout=None):
        await asyncio.sleep(30)
        return SandboxResult()


class _HangingProvider(_PkgProvider):
    sandbox_cls = _HangingSandbox


PKG_DOTTED = f"{__name__}._PkgProvider"
LEGACY_DOTTED = f"{__name__}._LegacyProvider"
ECOSYSTEM_ONLY_DOTTED = f"{__name__}._EcosystemOnlyProvider"
HANGING_DOTTED = f"{__name__}._HangingProvider"

INSTALL_ALL = PackageInstallPolicy(ecosystems=["python", "node"])


def _stop_leaked_thread_broker():
    """Stop the current manager's thread broker so its daemon thread doesn't leak across tests
    (the tests/test_sandbox_broker.py shape)."""
    mgr = ExecutionManager._instance
    broker = getattr(mgr, "_broker", None) if mgr is not None else None
    thread = getattr(broker, "_thread", None)
    if thread is not None and thread.is_alive():
        broker._closed = True
        broker._loop.call_soon_threadsafe(broker._queue.put_nowait, None)
        thread.join(5.0)


def _reset_all():
    AKConfig._reset()
    ExecutionManager._reset()
    SandboxProviderFactory._reset()
    InMemoryTransport.reset()
    InMemoryResponseStore.reset()
    ThreadRunner.shutdown_event.clear()
    Runtime._system_pre_hooks = None
    Runtime._system_post_hooks = None


@pytest.fixture(autouse=True)
def reset_singletons():
    _reset_all()
    _PkgSandbox.calls = []
    _LegacySandbox.calls = []
    _EcosystemOnlySandbox.calls = []
    yield
    _stop_leaked_thread_broker()
    _reset_all()


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
    for field in (f"operation={operation}", "profile=prof-a", "agent=agent-a", "ak_session_id=ak-1", "sandbox_session_id='sess-1'"):
        assert field in line
    # No code or package text reaches the log or the error.
    assert "zzq" not in line and "zzq" not in str(excinfo.value)
    assert str(excinfo.value).startswith(f"profile 'prof-a' does not permit {operation}: ")
    assert str(excinfo.value).endswith("this is a configuration decision, so do not retry it through run_command")


@pytest.mark.parametrize(
    "operation, payload, policy",
    [
        ("execute_code", {"code": "x", "language": "py\nthon"}, SandboxPolicy(languages=["python"])),
        ("install_packages", {"packages": ["x"], "ecosystem": "no\nde"}, SandboxPolicy(package_install=PackageInstallPolicy())),
    ],
    ids=["language", "ecosystem"],
)
def test_guard_escapes_request_supplied_names(caplog, operation, payload, policy):
    # The language/ecosystem and an explicit sandbox session id come from the model; a raw
    # newline in any of them would forge a second log line.
    context = _CONTEXT.model_copy(update={"sandbox_session_id": "se\nss"})
    with caplog.at_level("WARNING", logger=BROKER_LOGGER):
        with pytest.raises(SandboxPermissionDeniedError) as excinfo:
            SandboxPermissionGuard().check_operation(operation, payload, policy, context)
    line = _broker_records(caplog)[0].getMessage()
    assert "\n" not in line and "\n" not in str(excinfo.value)
    assert "\\n" in line


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


def _generic_failures(caplog):
    return [r for r in _broker_records(caplog) if r.getMessage().startswith("Sandbox task t-1 failed")]


@pytest.mark.asyncio
@pytest.mark.parametrize("site", ["process", "thread_broker"])
@pytest.mark.parametrize("check", ["check_principal", "enforce_policy"])
async def test_other_policy_failures_keep_the_generic_warning(monkeypatch, caplog, site, check):
    # Only SandboxPermissionDeniedError skips the generic warning; the fail-closed identity and
    # policy checks still log it, exactly once, on both process() and ThreadBroker._handle.
    if check == "check_principal":
        # A user-identity profile on a provider that does not declare principal_user.
        _use_provider(monkeypatch, identity=_SandboxIdentityConfig(mode="user"))
        request, error = _request(), SandboxCapabilityError
    else:
        # An unenforceable dimension under strict.
        _use_provider(monkeypatch)
        request, error = _request(policy=SandboxPolicy(network_egress="deny")), SandboxPolicyError
    with caplog.at_level("WARNING", logger=BROKER_LOGGER):
        if site == "process":
            completion = await BrokerWorkerCore().process(request)
            assert completion.status == "failed" and completion.error_type == error.__name__
        else:
            broker = ThreadBroker()
            try:
                with pytest.raises(error) as excinfo:
                    await broker.submit(request)
                assert not isinstance(excinfo.value, SandboxPermissionDeniedError)
            finally:
                await broker.close()
    assert len(_generic_failures(caplog)) == 1
    assert _denials(caplog) == []


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
async def test_mismatch_warning_is_per_profile(monkeypatch, caplog):
    # Two profiles on the same provider each get their own warning, still once each.
    profiles = {name: _SandboxProfileConfig(type=PKG_DOTTED) for name in ("alpha", "beta")}
    _install_cfg(monkeypatch, _SandboxConfig(enabled=True, broker=_ExecutionBrokerConfig(flavor="embedded"), profiles=profiles))
    worker = BrokerWorkerCore()
    policy = SandboxPolicy(package_install=INSTALL_ALL)
    with caplog.at_level("WARNING", logger=BROKER_LOGGER):
        for _ in range(2):
            for name in profiles:
                await worker.process(_request(policy=policy, profile=name))
    messages = sorted(r.getMessage() for r in _mismatch_records(caplog))
    assert len(messages) == 2
    assert messages[0].startswith("Sandbox profile alpha ") and messages[1].startswith("Sandbox profile beta ")


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
async def test_legacy_override_rejects_non_python_ecosystem(monkeypatch, caplog):
    _use_provider(monkeypatch, dotted=LEGACY_DOTTED)
    worker = BrokerWorkerCore()
    policy = SandboxPolicy(package_install=INSTALL_ALL)
    with caplog.at_level("WARNING", logger=BROKER_LOGGER):
        with pytest.raises(SandboxCapabilityError, match="package_ecosystem:node"):
            await worker.run(_install(["lodash"], "node", policy=policy))
        assert _LegacySandbox.calls == []
        # The rejected node request is not the first legacy call, so it logs no deprecation...
        assert _deprecations(caplog) == []
        # ...and the first python call still logs exactly one.
        await worker.run(_install(["requests"], policy=policy))
    assert _LegacySandbox.calls == [["requests"]]
    assert len(_deprecations(caplog)) == 1


class TestLegacyProviderContract(SandboxProviderContract):
    """A pre-#692 one-argument override still passes the public contract during the deprecation window."""

    @pytest.fixture
    def provider(self):
        _LegacySandbox.calls = []
        return _LegacyProvider()


def test_install_parameters_reads_each_signature_shape():
    both = frozenset({"ecosystem", "timeout"})
    assert BrokerWorkerCore.install_parameters(_PkgSandbox) == both
    assert BrokerWorkerCore.install_parameters(FakeSandbox) == both  # the base ABC's signature
    assert BrokerWorkerCore.install_parameters(_KwargsSandbox) == both
    assert BrokerWorkerCore.install_parameters(_EcosystemOnlySandbox) == {"ecosystem"}
    assert BrokerWorkerCore.install_parameters(_TimeoutOnlySandbox) == {"timeout"}
    assert BrokerWorkerCore.install_parameters(_LegacySandbox) == frozenset()


class TestEcosystemOnlyProviderContract(SandboxProviderContract):
    """An override with an ecosystem but no timeout passes the contract, including the undeclared-ecosystem check."""

    @pytest.fixture
    def provider(self):
        return _EcosystemOnlyProvider()


@pytest.mark.asyncio
async def test_ecosystem_only_override_gets_its_ecosystem_with_one_deprecation_warning(monkeypatch, caplog):
    # Only the missing timeout makes it pre-#692: a node install reaches it, not a capability error.
    _use_provider(monkeypatch, dotted=ECOSYSTEM_ONLY_DOTTED)
    worker = BrokerWorkerCore()
    with caplog.at_level("WARNING", logger=BROKER_LOGGER):
        r1, _ = await worker.run(_install(["lodash"], "node", policy=SandboxPolicy(package_install=INSTALL_ALL)))
        await worker.run(_install(["requests"], policy=SandboxPolicy(package_install=INSTALL_ALL)))
    assert r1.stdout == "ecosystem-only"
    assert _EcosystemOnlySandbox.calls == [(["lodash"], "node"), (["requests"], "python")]
    records = _deprecations(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    assert "_EcosystemOnlySandbox" in message and "without timeout;" in message


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


@pytest.mark.asyncio
async def test_backstop_adds_the_grace_on_top_of_the_effective_timeout(monkeypatch):
    # The worker's own timer is effective timeout + grace: it must not fire at the bare 0.05 s.
    _use_provider(monkeypatch, dotted=HANGING_DOTTED)
    monkeypatch.setattr("agentkernel.sandbox.broker.worker.BrokerWorkerCore.BACKSTOP_GRACE_SECONDS", 0.3)
    policy = SandboxPolicy(timeout=30, package_install=PackageInstallPolicy(timeout=0.05))
    started = time.monotonic()
    completion = await asyncio.wait_for(BrokerWorkerCore().process(_install(policy=policy)), timeout=5)
    elapsed = time.monotonic() - started
    assert completion.status == "timed_out"
    assert elapsed >= 0.3  # the grace was added (0.35 s backstop), not the bare install timeout
    assert elapsed < 5  # and well short of policy.timeout = 30


# --------------------------------------------------------------------------- #
# ExecutionManager (agent side)
# --------------------------------------------------------------------------- #


def _permits(ecosystems=None, timeout=None, **policy_kwargs):
    install = _SandboxPackageInstallConfig(**({"ecosystems": ecosystems} if ecosystems else {}), timeout=timeout)
    return _SandboxPolicyConfig(package_install=install, **policy_kwargs)


def _use_profiles(monkeypatch, profiles, flavor="embedded", **broker_kwargs):
    cfg = _SandboxConfig(enabled=True, broker=_ExecutionBrokerConfig(flavor=flavor, **broker_kwargs), profiles=profiles)
    _install_cfg(monkeypatch, cfg)
    return cfg


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["denied-ecosystem", "denied-language", "rejected-spec"])
async def test_agent_side_rejection_has_no_side_effects(monkeypatch, caplog, case):
    profile = _SandboxProfileConfig(type=PKG_DOTTED, policy=_permits(languages=["python"]))
    _use_profiles(monkeypatch, {"default": profile})
    mgr = ExecutionManager.get()
    session = InMemorySessionStore().new("ak-1")
    async with session:
        await mgr.execute(code="print(1)")  # gives the default session a live sandbox
        cache = session.get_non_volatile_cache()
        registry = cache.get("sandbox")
        registry["sessions"]["default:default"]["last_used_at"] = 0.0  # idle-expired: the next touch would tear it down
        cache.set("sandbox", registry)

        submitted = []

        async def record(request, wait=None):
            submitted.append(request.operation)

        monkeypatch.setattr(mgr._broker, "submit", record)
        with caplog.at_level("WARNING", logger=BROKER_LOGGER):
            if case == "denied-ecosystem":
                with pytest.raises(SandboxPermissionDeniedError):
                    await mgr.install_packages(["lodash"], ecosystem="node")
            elif case == "denied-language":
                with pytest.raises(SandboxPermissionDeniedError):
                    await mgr.execute(code="echo hi", language="bash")
            else:
                with pytest.raises(ValueError):
                    await mgr.install_packages(["-r"])
        sandbox_id = cache.get("sandbox")["sessions"]["default:default"]["sandbox_id"]
    assert submitted == []  # no submit, and no idle-teardown destroy (that goes through submit too)
    assert sandbox_id  # the idle-expired sandbox was not torn down
    assert len(_denials(caplog)) == (0 if case == "rejected-spec" else 1)


def test_policy_from_copies_the_permission_fields():
    profile = _SandboxProfileConfig(type=PKG_DOTTED, policy=_permits(["python", "node"], timeout=300, languages=["python"]))
    policy = ExecutionManager._policy_from(profile)
    assert policy.languages == ["python"]
    assert policy.package_install == PackageInstallPolicy(ecosystems=["python", "node"], timeout=300)
    plain = ExecutionManager._policy_from(_SandboxProfileConfig(type=PKG_DOTTED))
    assert plain.languages is None and plain.package_install is None


def test_permission_config_warnings_fire_once_per_profile(monkeypatch, caplog):
    profiles = {
        "shared": _SandboxProfileConfig(type=PKG_DOTTED, scope="per_runtime", policy=_permits()),
        "offline": _SandboxProfileConfig(type=PKG_DOTTED, policy=_permits(network_egress="deny")),
        "locked": _SandboxProfileConfig(type="docker", docker=_SandboxDockerConfig(), policy=_permits(fs_allow_write=["/workspace"])),
        # Every risky setting, but no package_install block: no warning.
        "quiet": _SandboxProfileConfig(
            type="docker",
            scope="per_runtime",
            docker=_SandboxDockerConfig(),
            policy=_SandboxPolicyConfig(network_egress="deny", fs_allow_write=["/workspace"]),
        ),
    }
    _use_profiles(monkeypatch, profiles)
    with caplog.at_level("WARNING", logger="ak.sandbox"):
        ExecutionManager.get()
        ExecutionManager.get()  # the singleton: no second round of warnings
    messages = [r.getMessage() for r in caplog.records if r.name == "ak.sandbox"]
    assert len(messages) == 3
    assert any("shared" in m and "per_runtime" in m for m in messages)
    assert any("offline" in m and "mirror" in m for m in messages)
    assert any("locked" in m and "--target" in m and "PYTHONPATH" in m for m in messages)
    assert not any("quiet" in m for m in messages)


@pytest.mark.asyncio
async def test_agent_side_validation_uses_the_profiles_provider_block(monkeypatch):
    docker = _SandboxDockerConfig(package_installers={"python": ["pip", "install"], "node": ["npm", "install"]})
    profiles = {
        "docker": _SandboxProfileConfig(type="docker", docker=docker, policy=_permits(["python", "node"])),
        "fake": _SandboxProfileConfig(type=PKG_DOTTED, policy=_permits()),
    }
    _use_profiles(monkeypatch, profiles)
    mgr = ExecutionManager.get()

    # The docker block's node rule applies agent-side, before anything reaches the provider.
    with pytest.raises(ValueError):
        await mgr.install_packages(["zzq/zzrepo"], ecosystem="node", profile="docker")
    installer = mgr._installer_for("docker", profiles["docker"])
    assert installer.ecosystems == ["python", "node"]
    assert mgr._installer_for("docker", profiles["docker"]) is installer  # cached per profile

    # A provider without a package block: the baseline only; the worker's handle decides the rest.
    baseline = mgr._installer_for("fake", profiles["fake"])
    assert baseline.ecosystems == []
    baseline.validate(["sub/pkg"], "python")
    with pytest.raises(ValueError):
        baseline.validate(["-r"], "python")


# --------------------------------------------------------------------------- #
# End to end: ExecutionManager.install_packages over every flavor
# --------------------------------------------------------------------------- #


def _installing_profile():
    """A default profile on the package-capable fake that permits python installs with their own timeout."""
    return {"default": _SandboxProfileConfig(type=PKG_DOTTED, policy=_permits(timeout=300))}


@pytest.mark.asyncio
@pytest.mark.parametrize("flavor", ["embedded", "thread"])
async def test_install_end_to_end_in_process(monkeypatch, flavor):
    _use_profiles(monkeypatch, _installing_profile(), flavor=flavor)
    session = InMemorySessionStore().new("ak-1")
    async with session:
        result = await ExecutionManager.get().install_packages(["requests"], wait=10)
    assert result.stdout == "installed" and result.sandbox_session_id == "default:default"
    assert _PkgSandbox.calls == [(["requests"], "python", 300)]  # the install's own effective timeout


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "languages, language",
    [(None, "python"), (None, "bash"), (["python", "bash"], "bash")],
    ids=["provider-declared-python", "provider-declared-bash", "listed-bash"],
)
async def test_permitted_run_code_end_to_end(monkeypatch, languages, language):
    # languages=None leaves the provider's own list in force; a listed language passes both checks.
    profile = _SandboxProfileConfig(type=PKG_DOTTED, policy=_SandboxPolicyConfig(languages=languages))
    _use_profiles(monkeypatch, {"default": profile})
    session = InMemorySessionStore().new("ak-1")
    async with session:
        result = await ExecutionManager.get().execute(code="echo zzq", language=language)
    assert result.exit_code == 0 and result.stdout == "echo zzq"  # FakeSandbox echoes the code


@pytest.mark.asyncio
async def test_install_end_to_end_over_the_queue_flavor(monkeypatch):
    cfg = _use_profiles(
        monkeypatch,
        _installing_profile(),
        flavor="queue",
        queue=_QueuesConfig(type="in_memory"),
        response_store=_ResponseStoreConfig(type="in_memory"),
        wait_poll_interval=0.01,
    )
    worker = QueueBrokerWorker(cfg)
    runner = threading.Thread(target=lambda: worker.start(exit_on_shutdown=False), daemon=True)
    runner.start()
    try:
        session = InMemorySessionStore().new("ak-1")
        async with session:
            result = await ExecutionManager.get().install_packages(["requests"], wait=10)
        assert result.stdout == "installed"
        assert _PkgSandbox.calls == [(["requests"], "python", 300)]  # the permission survived the wire
    finally:
        ThreadRunner.shutdown_event.set()
        runner.join(timeout=10)
    assert not runner.is_alive()


# --------------------------------------------------------------------------- #
# The install_packages tool
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_install_packages_tool_json_contract(monkeypatch, caplog):
    _use_profiles(monkeypatch, _installing_profile())
    session = InMemorySessionStore().new("ak-1")
    async with session:
        ok = json.loads(await install_packages_tool(["requests"]))
        with caplog.at_level("WARNING", logger="ak.sandbox.tools"):
            denied = json.loads(await install_packages_tool(["lodash"], ecosystem="node"))
    assert ok == {"stdout": "installed", "stderr": "", "exit_code": 0, "sandbox_session_id": "default:default"}
    assert "does not permit install_packages" in denied["error"]
    assert any(r.name == "ak.sandbox.tools" for r in caplog.records)


_TOOL_BUILDERS = [
    ("agentkernel.framework.openai.openai", "OpenAIToolBuilder"),
    ("agentkernel.framework.langgraph.langgraph", "LangGraphToolBuilder"),
    ("agentkernel.framework.crewai.crewai", "CrewAIToolBuilder"),
    ("agentkernel.framework.pydanticai.pydanticai", "PydanticAIToolBuilder"),
    ("agentkernel.framework.smolagents.smolagents", "SmolagentsToolBuilder"),
    ("agentkernel.framework.adk.adk", "GoogleADKToolBuilder"),
]


def _packages_schema(tool):
    """The bound tool's JSON schema for ``packages``, where the adapter exposes one; else None."""
    if hasattr(tool, "params_json_schema"):  # openai
        return tool.params_json_schema["properties"]["packages"]
    if hasattr(tool, "function_schema"):  # pydanticai
        return tool.function_schema.json_schema["properties"]["packages"]
    if hasattr(tool, "inputs"):  # smolagents
        return tool.inputs["packages"]
    args_schema = getattr(tool, "args_schema", None)  # langgraph, crewai
    if args_schema is not None:
        schema = args_schema if isinstance(args_schema, dict) else args_schema.model_json_schema()
        return schema["properties"]["packages"]
    return None


@pytest.mark.parametrize("module_name, builder_name", _TOOL_BUILDERS, ids=[name for name, _ in _TOOL_BUILDERS])
def test_install_packages_tool_binds_on_every_adapter(module_name, builder_name):
    # install_packages is the first system tool with a non-scalar parameter (list[str]); it must
    # bind wherever the existing sandbox tools do. (smolagents cannot bind any async sandbox tool
    # today, run_code included, so there it only has to fail the same way.)
    module = pytest.importorskip(module_name)
    builder = getattr(module, builder_name)
    try:
        builder.bind([run_code_tool])
    except Exception as exc:  # noqa: BLE001 — a pre-existing adapter limitation, not this tool's
        with pytest.raises(type(exc)):
            builder.bind([install_packages_tool])
        return
    [tool] = builder.bind([install_packages_tool])
    assert tool.name == "install_packages"
    schema = _packages_schema(tool)
    if schema is not None:
        assert schema["type"] == "array"
        if "items" in schema:
            assert schema["items"]["type"] == "string"
