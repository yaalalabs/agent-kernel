"""Tests for the sandbox capability core: data types, error hierarchy, config, the provider
ABC/contract, the manager + factory + embedded broker end-to-end, and the agent surface
(system tools + task-completion pre-hook).

Broker-flavor mechanics (thread/sqs) and the concrete providers are covered by later
iterations in test_sandbox_broker.py / test_sandbox_providers.py.
"""

import json
import types

import pytest
from pydantic import BaseModel, ValidationError

from agentkernel.core.base import Session
from agentkernel.core.config import (
    AKConfig,
    _SandboxBrokerConfig,
    _SandboxConfig,
    _SandboxDockerConfig,
    _SandboxIdentityConfig,
    _SandboxPolicyConfig,
    _SandboxProfileConfig,
)
from agentkernel.core.model import AgentReplyText, AgentRequestAny, AgentRequestText
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.tool import SystemToolFactory
from agentkernel.sandbox import errors
from agentkernel.sandbox.base import Sandbox
from agentkernel.sandbox.broker.base import SandboxCompletion
from agentkernel.sandbox.errors import SandboxCapabilityError, SandboxConfigError, SandboxPolicyError, SandboxSessionNotFoundError
from agentkernel.sandbox.factory import SandboxProviderFactory
from agentkernel.sandbox.hooks import NoOpSandboxPreHook, SandboxPreHook, SandboxPreHookFactory
from agentkernel.sandbox.manager import SandboxManager
from agentkernel.sandbox.model import (
    IsolationTier,
    SandboxCapabilities,
    SandboxPolicy,
    SandboxPrincipal,
    SandboxResult,
    SandboxSession,
    SandboxTask,
)
from agentkernel.sandbox.principal import AgentPrincipalResolver
from agentkernel.sandbox.testing import FakeSandboxProvider, SandboxProviderContract
from agentkernel.sandbox.tools import check_sandbox_task, get_sandbox_tools, read_sandbox_file, run_code, run_command, write_sandbox_file


@pytest.fixture(autouse=True)
def reset_config_singleton():
    AKConfig._reset()
    SandboxManager._reset()
    SandboxProviderFactory._reset()
    yield
    AKConfig._reset()
    SandboxManager._reset()
    SandboxProviderFactory._reset()


FAKE_DOTTED = "agentkernel.sandbox.testing.FakeSandboxProvider"


def _install_sandbox_cfg(monkeypatch, sandbox_cfg):
    """Point AKConfig.get() at a stub carrying only the sandbox section."""

    class _Cfg:
        sandbox = sandbox_cfg
        multimodal = None  # read by SystemToolFactory.get_all() alongside the sandbox block

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))


def _sandbox_cfg(profiles=None, **overrides):
    if profiles is None:
        profiles = {"default": _SandboxProfileConfig(type=FAKE_DOTTED, scope="per_session")}
    return _SandboxConfig(enabled=True, broker=_SandboxBrokerConfig(flavor="embedded"), profiles=profiles, **overrides)


# --------------------------------------------------------------------------- #
# Data types (model.py)
# --------------------------------------------------------------------------- #


def test_model_package_public_exports():
    """agentkernel.sandbox imports cleanly and exposes the data types + errors module."""
    import agentkernel.sandbox as sandbox

    assert sandbox.SandboxResult is SandboxResult
    assert sandbox.IsolationTier is IsolationTier
    assert sandbox.errors.SandboxError is errors.SandboxError


def test_model_capabilities_defaults():
    caps = SandboxCapabilities(isolation=IsolationTier.CONTAINER)
    # languages defaults to python only; every optional capability is off by default
    assert caps.languages == ["python"]
    assert caps.isolation is IsolationTier.CONTAINER
    for flag in (
        caps.shell,
        caps.files,
        caps.package_install,
        caps.stateful,
        caps.attach,
        caps.principal_user,
        caps.policy_network,
        caps.policy_filesystem,
        caps.policy_resources,
    ):
        assert flag is False


def test_model_capabilities_isolation_is_required():
    # IsolationTier is mandatory and has no default — honesty about the boundary.
    with pytest.raises(ValidationError):
        SandboxCapabilities()


def test_model_result_nonzero_exit_is_data_not_error():
    # A failing program is a SandboxResult, never an exception.
    result = SandboxResult(stdout="", stderr="boom", exit_code=1)
    assert result.exit_code == 1
    assert result.stderr == "boom"
    assert result.output_files == []
    assert result.provider_data == {}
    assert result.sandbox_session_id == ""


def test_model_policy_and_principal_defaults():
    policy = SandboxPolicy()
    assert policy.network_egress == "allow"
    assert policy.timeout == 120.0
    assert policy.strict is True
    assert policy.cpu is None and policy.memory_mb is None

    principal = SandboxPrincipal(subject="agent-x")
    assert principal.mode == "agent"
    assert principal.subject == "agent-x"
    assert principal.credentials == {} and principal.groups == []

    # subject is required
    with pytest.raises(ValidationError):
        SandboxPrincipal()


def test_errors_hierarchy():
    # Every sandbox error derives from SandboxError; SandboxGoneError is a provision error.
    for exc in (
        errors.SandboxConfigError,
        errors.SandboxCapabilityError,
        errors.SandboxPolicyError,
        errors.SandboxTimeoutError,
        errors.SandboxProvisionError,
        errors.SandboxGoneError,
        errors.SandboxSessionNotFoundError,
        errors.SandboxBrokerError,
    ):
        assert issubclass(exc, errors.SandboxError)
    assert issubclass(errors.SandboxGoneError, errors.SandboxProvisionError)


# --------------------------------------------------------------------------- #
# Config (core/config.py)
# --------------------------------------------------------------------------- #


def test_config_sandbox_defaults(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    cfg = AKConfig.get()
    sb = cfg.sandbox
    assert sb.enabled is False
    assert sb.default_profile == "default"
    assert sb.principal_resolver is None
    assert sb.tool_output_max_chars == 8000
    assert sb.profiles == {}
    # broker defaults
    assert sb.broker.flavor == "thread"
    assert sb.broker.wait_timeout == 60.0
    assert sb.broker.inline_payload_max_bytes == 131072
    assert sb.broker.worker_timeout_ceiling is None


def test_config_disabled_by_default_is_inert(monkeypatch):
    # With no sandbox config, the capability is inert: disabled and no profiles.
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    cfg = AKConfig.get()
    assert cfg.sandbox.enabled is False
    assert cfg.sandbox.profiles == {}


def test_config_single_backend_sugar_synthesizes_default_profile():
    # type set + no profiles -> profiles["default"] synthesized from the sugar fields.
    sb = _SandboxConfig(type="docker", docker=_SandboxDockerConfig(image="custom:latest"))
    assert "default" in sb.profiles
    default = sb.profiles["default"]
    assert default.type == "docker"
    assert default.scope == "per_session"  # profile default carries through
    assert default.docker is not None and default.docker.image == "custom:latest"


def test_config_sugar_respects_custom_default_profile_and_scope():
    sb = _SandboxConfig(type="e2b", scope="per_runtime", default_profile="main")
    assert set(sb.profiles) == {"main"}
    assert sb.profiles["main"].type == "e2b"
    assert sb.profiles["main"].scope == "per_runtime"


def test_config_explicit_profiles_skip_sugar():
    # An explicit profiles map always wins; the sugar does not overwrite it.
    sb = _SandboxConfig(type="docker", profiles={"p1": _SandboxProfileConfig(type="e2b")})
    assert set(sb.profiles) == {"p1"}
    assert "default" not in sb.profiles


def test_config_env_override(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    monkeypatch.setenv("AK_SANDBOX__ENABLED", "true")
    monkeypatch.setenv("AK_SANDBOX__BROKER__FLAVOR", "embedded")
    monkeypatch.setenv("AK_SANDBOX__TOOL_OUTPUT_MAX_CHARS", "1234")
    monkeypatch.setenv("AK_SANDBOX__TYPE", "docker")  # single-backend sugar via env

    cfg = AKConfig()
    assert cfg.sandbox.enabled is True
    assert cfg.sandbox.broker.flavor == "embedded"
    assert cfg.sandbox.tool_output_max_chars == 1234
    # sugar synthesis still runs after env-sourced fields are set
    assert cfg.sandbox.profiles["default"].type == "docker"


# --------------------------------------------------------------------------- #
# ABCs, provider contract, principal resolver (base.py / testing.py / principal.py)
# --------------------------------------------------------------------------- #


class TestFakeProviderContract(SandboxProviderContract):
    """Run the reusable provider contract suite against FakeSandboxProvider."""

    @pytest.fixture
    def provider(self):
        return FakeSandboxProvider()


@pytest.mark.asyncio
async def test_capability_matrix_undeclared_ops_raise():
    # The fake declares package_install=False, so the base ABC raises for it, while the
    # declared operations (shell, files) succeed.
    provider = FakeSandboxProvider()
    sandbox = await provider.create(principal=SandboxPrincipal(subject="a"), policy=SandboxPolicy())
    try:
        assert (await sandbox.execute_command("echo hi")).exit_code == 0
        await sandbox.upload_file("f.txt", b"x")
        assert await sandbox.download_file("f.txt") == b"x"
        with pytest.raises(SandboxCapabilityError):
            await sandbox.install_packages(["pkg"])
    finally:
        await sandbox.close()


@pytest.mark.asyncio
async def test_capability_abc_defaults_raise_for_optional_ops():
    # A minimal Sandbox overriding only the mandatory surface inherits the raising
    # defaults for every optional operation.
    class _MinimalSandbox(Sandbox):
        def __init__(self):
            self.id = "minimal"

        async def execute_code(self, code, language="python", timeout=None):
            return SandboxResult(stdout=code)

        async def close(self):
            pass

    sandbox = _MinimalSandbox()
    with pytest.raises(SandboxCapabilityError):
        await sandbox.execute_command("x")
    with pytest.raises(SandboxCapabilityError):
        await sandbox.upload_file("p", b"")
    with pytest.raises(SandboxCapabilityError):
        await sandbox.download_file("p")
    with pytest.raises(SandboxCapabilityError):
        await sandbox.install_packages(["p"])


def test_capability_error_message_forms():
    two = SandboxCapabilityError("DockerSandbox", "shell")
    assert two.subject == "DockerSandbox" and two.capability == "shell"
    assert "shell" in str(two)

    one = SandboxCapabilityError("principal_user")
    assert one.subject is None and one.capability == "principal_user"
    assert "principal_user" in str(one)


@pytest.mark.asyncio
async def test_principal_resolver_default_agent_identity():
    class _StubAgent:
        name = "stub-agent"

    principal = await AgentPrincipalResolver().resolve(Session("s1"), _StubAgent())
    assert principal.mode == "agent"
    assert principal.subject == "stub-agent"
    assert principal.credentials == {}
    assert principal.groups == []


@pytest.mark.asyncio
async def test_principal_resolver_tolerates_no_agent():
    principal = await AgentPrincipalResolver().resolve(Session("s1"), None)
    assert principal.mode == "agent"
    assert principal.subject == "agent"


# --------------------------------------------------------------------------- #
# Factory resolution matrix (factory.py)
# --------------------------------------------------------------------------- #


def test_factory_disabled_returns_none(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _SandboxConfig(enabled=False))
    assert SandboxProviderFactory.get() is None
    assert SandboxManager.get() is None


def test_factory_unknown_profile_raises(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    with pytest.raises(SandboxConfigError):
        SandboxProviderFactory.get("ghost")


def test_factory_dotted_path_resolves(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    assert isinstance(SandboxProviderFactory.get("default"), FakeSandboxProvider)


def test_factory_dotted_path_is_cached(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    first = SandboxProviderFactory.get("default")
    second = SandboxProviderFactory.get("default")
    assert first is second


def test_factory_non_subclass_dotted_path_raises(monkeypatch):
    cfg = _sandbox_cfg(profiles={"default": _SandboxProfileConfig(type="agentkernel.sandbox.model.SandboxResult")})
    _install_sandbox_cfg(monkeypatch, cfg)
    with pytest.raises(SandboxConfigError):
        SandboxProviderFactory.get("default")


def test_factory_dotted_path_config_model_validates_params(monkeypatch):
    class _CfgModel(BaseModel):
        image: str

    class _Prov(FakeSandboxProvider):
        config_model = _CfgModel

    # BYO dotted-path resolution goes through the shared helper, so patch its importlib.
    import agentkernel.core.util.factory as fac

    real = fac.importlib.import_module
    monkeypatch.setattr(
        fac.importlib,
        "import_module",
        lambda name, *a, **k: types.SimpleNamespace(Prov=_Prov) if name == "fake_mod" else real(name, *a, **k),
    )
    cfg = _sandbox_cfg(profiles={"default": _SandboxProfileConfig(type="fake_mod.Prov", params={"image": "custom:1"})})
    _install_sandbox_cfg(monkeypatch, cfg)
    provider = SandboxProviderFactory.get("default")
    assert isinstance(provider, _Prov)
    assert isinstance(provider._config, _CfgModel)
    assert provider._config.image == "custom:1"


def _patch_provider_import(monkeypatch, module_name, result_or_exc):
    import agentkernel.sandbox.factory as fac

    real = fac.importlib.import_module

    def fake(name, *a, **k):
        if name == module_name:
            if isinstance(result_or_exc, Exception):
                raise result_or_exc
            return result_or_exc
        return real(name, *a, **k)

    monkeypatch.setattr(fac.importlib, "import_module", fake)


def test_factory_builtin_missing_extra_raises_import_error(monkeypatch):
    cfg = _sandbox_cfg(profiles={"default": _SandboxProfileConfig(type="docker", docker=_SandboxDockerConfig())})
    _install_sandbox_cfg(monkeypatch, cfg)
    _patch_provider_import(monkeypatch, "agentkernel.sandbox.providers.docker", ImportError("No module named 'docker'"))
    with pytest.raises(ImportError) as exc_info:
        SandboxProviderFactory.get("default")
    assert "agentkernel[sandbox-docker]" in str(exc_info.value)


def test_factory_builtin_lazy_import_success(monkeypatch):
    cfg = _sandbox_cfg(profiles={"default": _SandboxProfileConfig(type="docker", docker=_SandboxDockerConfig())})
    _install_sandbox_cfg(monkeypatch, cfg)
    _patch_provider_import(monkeypatch, "agentkernel.sandbox.providers.docker", types.SimpleNamespace(DockerSandboxProvider=FakeSandboxProvider))
    assert isinstance(SandboxProviderFactory.get("default"), FakeSandboxProvider)


def test_factory_builtin_missing_config_block_raises(monkeypatch):
    cfg = _sandbox_cfg(profiles={"default": _SandboxProfileConfig(type="docker")})  # no docker block
    _install_sandbox_cfg(monkeypatch, cfg)
    _patch_provider_import(monkeypatch, "agentkernel.sandbox.providers.docker", types.SimpleNamespace(DockerSandboxProvider=FakeSandboxProvider))
    with pytest.raises(SandboxConfigError):
        SandboxProviderFactory.get("default")


def test_manager_build_resolver_custom_and_invalid():
    resolver = SandboxManager._build_resolver(_sandbox_cfg(principal_resolver="agentkernel.sandbox.principal.AgentPrincipalResolver"))
    assert isinstance(resolver, AgentPrincipalResolver)
    with pytest.raises(SandboxConfigError):
        SandboxManager._build_resolver(_sandbox_cfg(principal_resolver="agentkernel.sandbox.model.SandboxResult"))


# --------------------------------------------------------------------------- #
# SandboxManager end-to-end via the embedded broker (manager.py / broker/*)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_manager_execute_code_and_command(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    mgr = SandboxManager.get()
    session = InMemorySessionStore().new("ak-1")
    async with session:
        code_result = await mgr.execute(code="print('hi')")
        cmd_result = await mgr.execute(command="echo hi")
    assert code_result.exit_code == 0 and code_result.stdout == "print('hi')"
    assert cmd_result.exit_code == 0 and cmd_result.stdout == "echo hi"
    assert code_result.sandbox_session_id == "default:default"


@pytest.mark.asyncio
async def test_manager_session_round_trip_and_reuse(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    mgr = SandboxManager.get()
    store = InMemorySessionStore()
    session = store.new("ak-1")
    async with session:
        r1 = await mgr.execute(code="print(1)")
    # round-trip the session (and its nv_cache registry) through the store
    store.store(session)
    loaded = store.load("ak-1")
    async with loaded:
        r2 = await mgr.execute(code="print(2)")
    provider = SandboxProviderFactory.get("default")
    assert len(provider.created_ids) == 1  # reused, not recreated
    assert r1.sandbox_session_id == r2.sandbox_session_id == "default:default"


@pytest.mark.asyncio
async def test_manager_unknown_session_id_raises(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    mgr = SandboxManager.get()
    session = InMemorySessionStore().new("ak-1")
    async with session:
        with pytest.raises(SandboxSessionNotFoundError):
            await mgr.execute(code="print(1)", sandbox_session_id="does-not-exist")


@pytest.mark.asyncio
async def test_manager_cross_session_isolation(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    mgr = SandboxManager.get()
    store = InMemorySessionStore()
    a = store.new("ak-a")
    b = store.new("ak-b")
    async with a:
        await mgr.execute(code="print(1)")
        a_sid = mgr.list_sessions()[0].sandbox_session_id
    async with b:
        # b's registry does not contain a's session id
        with pytest.raises(SandboxSessionNotFoundError):
            await mgr.execute(code="print(2)", sandbox_session_id=a_sid)
        # b can create its own default session independently
        await mgr.execute(code="print(3)")
        assert len(mgr.list_sessions()) == 1


@pytest.mark.asyncio
async def test_manager_stale_handle_self_heal(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    mgr = SandboxManager.get()
    provider = SandboxProviderFactory.get("default")
    session = InMemorySessionStore().new("ak-1")
    async with session:
        await mgr.execute(code="print(1)")
        vanished = provider.created_ids[0]
        provider._sandboxes.pop(vanished)  # simulate the backend sandbox disappearing
        await mgr.execute(code="print(2)")  # attach -> SandboxGoneError -> recreate
    assert len(provider.created_ids) == 2
    assert provider.created_ids[0] != provider.created_ids[1]


@pytest.mark.asyncio
async def test_manager_idle_timeout_recreates_on_touch(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    mgr = SandboxManager.get()
    provider = SandboxProviderFactory.get("default")
    session = InMemorySessionStore().new("ak-1")
    async with session:
        await mgr.execute(code="print(1)")
        first_id = provider.created_ids[0]
        # backdate last_used_at so the next touch treats the session as idle-expired
        registry = session.get_non_volatile_cache().get("sandbox")
        registry["sessions"]["default:default"]["last_used_at"] = 0.0
        await mgr.execute(code="print(2)")
    assert len(provider.created_ids) == 2
    assert first_id in provider.destroyed_ids


@pytest.mark.asyncio
async def test_manager_per_call_scope_creates_and_destroys(monkeypatch):
    profile = _SandboxProfileConfig(type=FAKE_DOTTED, scope="per_call")
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg(profiles={"default": profile}))
    mgr = SandboxManager.get()
    provider = SandboxProviderFactory.get("default")
    session = InMemorySessionStore().new("ak-1")
    async with session:
        await mgr.execute(code="print(1)")
        await mgr.execute(code="print(2)")
    assert len(provider.created_ids) == 2  # fresh per call
    assert len(provider.destroyed_ids) == 2  # each torn down


@pytest.mark.asyncio
async def test_manager_per_runtime_shared_across_ak_sessions(monkeypatch):
    # per_runtime maps to exactly one shared sandbox session per profile, in process memory,
    # reused across distinct AK sessions (no pooling in v1).
    profile = _SandboxProfileConfig(type=FAKE_DOTTED, scope="per_runtime")
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg(profiles={"default": profile}))
    mgr = SandboxManager.get()
    provider = SandboxProviderFactory.get("default")
    store = InMemorySessionStore()
    a = store.new("ak-a")
    b = store.new("ak-b")
    async with a:
        r1 = await mgr.execute(code="print(1)")
    async with b:
        r2 = await mgr.execute(code="print(2)")
    assert len(provider.created_ids) == 1  # one shared sandbox across both AK sessions
    assert r1.sandbox_session_id == r2.sandbox_session_id == "default:default"


@pytest.mark.asyncio
async def test_manager_upload_download_round_trip(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    mgr = SandboxManager.get()
    session = InMemorySessionStore().new("ak-1")
    async with session:
        await mgr.upload("data.txt", b"hello")
        content = await mgr.download("data.txt")
    assert content == b"hello"


@pytest.mark.asyncio
async def test_manager_destroy_session(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    mgr = SandboxManager.get()
    provider = SandboxProviderFactory.get("default")
    session = InMemorySessionStore().new("ak-1")
    async with session:
        await mgr.execute(code="print(1)")
        sid = mgr.list_sessions()[0].sandbox_session_id
        await mgr.destroy_session(sid)
        assert mgr.list_sessions() == []
        await mgr.destroy_session(sid)  # idempotent
    assert len(provider.destroyed_ids) >= 1


# --------------------------------------------------------------------------- #
# Fail-closed principal / policy enforcement (broker/worker.py)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_fail_closed_user_mode_unsupported_provider(monkeypatch):
    profile = _SandboxProfileConfig(type=FAKE_DOTTED, identity=_SandboxIdentityConfig(mode="user"))
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg(profiles={"default": profile}))
    mgr = SandboxManager.get()
    session = InMemorySessionStore().new("ak-1")
    async with session:
        with pytest.raises(SandboxCapabilityError):
            await mgr.execute(code="print(1)")


@pytest.mark.asyncio
async def test_fail_closed_user_mode_resolver_returns_agent(monkeypatch):
    user_caps = FakeSandboxProvider.capabilities.model_copy(update={"principal_user": True})
    monkeypatch.setattr(FakeSandboxProvider, "capabilities", user_caps)
    profile = _SandboxProfileConfig(type=FAKE_DOTTED, identity=_SandboxIdentityConfig(mode="user"))
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg(profiles={"default": profile}))
    mgr = SandboxManager.get()
    session = InMemorySessionStore().new("ak-1")
    async with session:
        with pytest.raises(SandboxPolicyError):
            await mgr.execute(code="print(1)")


@pytest.mark.asyncio
async def test_fail_closed_policy_strict(monkeypatch):
    profile = _SandboxProfileConfig(type=FAKE_DOTTED, policy=_SandboxPolicyConfig(network_egress="deny", strict=True))
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg(profiles={"default": profile}))
    mgr = SandboxManager.get()
    session = InMemorySessionStore().new("ak-1")
    async with session:
        with pytest.raises(SandboxPolicyError):
            await mgr.execute(code="print(1)")


@pytest.mark.asyncio
async def test_policy_non_strict_proceeds_with_warning(monkeypatch):
    profile = _SandboxProfileConfig(type=FAKE_DOTTED, policy=_SandboxPolicyConfig(network_egress="deny", strict=False))
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg(profiles={"default": profile}))
    mgr = SandboxManager.get()
    session = InMemorySessionStore().new("ak-1")
    async with session:
        result = await mgr.execute(code="print(1)")
    assert result.exit_code == 0


# --------------------------------------------------------------------------- #
# System tools (tools.py) — iteration 4
# --------------------------------------------------------------------------- #

SANDBOX_TOOL_NAMES = ["run_code", "run_command", "write_sandbox_file", "read_sandbox_file", "check_sandbox_task"]


def test_tools_registered_when_enabled(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    names = [tool.name for tool in SystemToolFactory.get_all()]
    assert names == SANDBOX_TOOL_NAMES


def test_tools_absent_when_disabled(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _SandboxConfig(enabled=False))
    assert SystemToolFactory.get_all() == []


def test_tool_descriptions_render_profiles_and_truncation(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg(tool_output_max_chars=1234))
    guidance = get_sandbox_tools()[0].description
    assert "'default' (default)" in guidance
    assert FAKE_DOTTED in guidance
    assert "per_session" in guidance
    assert "1234" in guidance


@pytest.mark.asyncio
async def test_tool_run_code_json_contract(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    session = InMemorySessionStore().new("ak-1")
    async with session:
        payload = json.loads(await run_code("print('hi')"))
    assert payload == {"stdout": "print('hi')", "stderr": "", "exit_code": 0, "sandbox_session_id": "default:default"}


@pytest.mark.asyncio
async def test_tool_run_command_json_contract(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    session = InMemorySessionStore().new("ak-1")
    async with session:
        payload = json.loads(await run_command("echo hi"))
    assert payload["stdout"] == "echo hi"
    assert payload["exit_code"] == 0
    assert payload["sandbox_session_id"] == "default:default"


@pytest.mark.asyncio
async def test_tool_file_roundtrip(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    session = InMemorySessionStore().new("ak-1")
    async with session:
        written = json.loads(await write_sandbox_file("notes.txt", "hello sandbox"))
        read = json.loads(await read_sandbox_file("notes.txt"))
    assert written == {"path": "notes.txt", "written": True, "sandbox_session_id": "default:default"}
    assert read == {"path": "notes.txt", "content": "hello sandbox", "sandbox_session_id": "default:default"}


@pytest.mark.asyncio
async def test_tool_output_truncated_at_configured_max(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg(tool_output_max_chars=5))
    session = InMemorySessionStore().new("ak-1")
    async with session:
        code_payload = json.loads(await run_code("0123456789"))  # fake echoes code to stdout
        await write_sandbox_file("big.txt", "0123456789")
        read_payload = json.loads(await read_sandbox_file("big.txt"))
    assert code_payload["stdout"] == "01234"
    assert read_payload["content"] == "01234"


@pytest.mark.asyncio
async def test_tool_machinery_error_returned_as_json(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    session = InMemorySessionStore().new("ak-1")
    async with session:
        payload = json.loads(await run_code("print(1)", profile="no-such-profile"))
    assert "no-such-profile" in payload["error"]


@pytest.mark.asyncio
async def test_tool_disabled_returns_error_json(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _SandboxConfig(enabled=False))
    payload = json.loads(await run_code("print(1)"))
    assert payload == {"error": "sandbox capability is disabled"}


@pytest.mark.asyncio
async def test_tool_check_task_unknown(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    session = InMemorySessionStore().new("ak-1")
    async with session:
        payload = json.loads(await check_sandbox_task("no-such-task"))
    assert payload == {"task_id": "no-such-task", "status": "unknown"}


# --------------------------------------------------------------------------- #
# Task-completion ingestion (hooks.py) — iteration 4
# --------------------------------------------------------------------------- #


def _completion(task_id, sandbox_session_id="default:default", status="succeeded", stdout="task output", **kwargs):
    return SandboxCompletion(
        task_id=task_id,
        status=status,
        result=SandboxResult(stdout=stdout, exit_code=0, sandbox_session_id=sandbox_session_id),
        sandbox_session=SandboxSession(
            sandbox_session_id=sandbox_session_id, profile="default", provider_type=FAKE_DOTTED, sandbox_id="sb-1", created_at=1.0, last_used_at=2.0
        ),
        **kwargs,
    )


def _seed_task(session, task_id, consumed=False):
    task = SandboxTask(task_id=task_id, sandbox_session_id="default:default", profile="default", submitted_at=0.0, consumed=consumed)
    session.get_non_volatile_cache().set("sandbox", {"sessions": {}, "tasks": {task_id: task.model_dump()}})


def test_hook_factory_gates_on_enabled(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    assert isinstance(SandboxPreHookFactory.get(), SandboxPreHook)
    _install_sandbox_cfg(monkeypatch, _SandboxConfig(enabled=False))
    assert isinstance(SandboxPreHookFactory.get(), NoOpSandboxPreHook)


@pytest.mark.asyncio
async def test_hook_passthrough_without_completion(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    requests = [AgentRequestText(prompt="hello")]
    session = InMemorySessionStore().new("ak-1")
    async with session:
        assert await SandboxPreHook().on_run(session, None, requests) is requests


@pytest.mark.asyncio
async def test_hook_unknown_task_halts(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    session = InMemorySessionStore().new("ak-1")
    requests = [AgentRequestAny(name="sandbox_task_completion", content=_completion("no-such-task").model_dump())]
    async with session:
        reply = await SandboxPreHook().on_run(session, None, requests)
    assert isinstance(reply, AgentReplyText)
    assert "Duplicate or unknown" in reply.response


@pytest.mark.asyncio
async def test_hook_consumed_duplicate_halts(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    session = InMemorySessionStore().new("ak-1")
    requests = [AgentRequestAny(name="sandbox_task_completion", content=_completion("t-1").model_dump())]
    async with session:
        _seed_task(session, "t-1", consumed=True)
        reply = await SandboxPreHook().on_run(session, None, requests)
    assert isinstance(reply, AgentReplyText)
    assert "Duplicate or unknown" in reply.response


@pytest.mark.asyncio
async def test_hook_malformed_completion_halts(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    session = InMemorySessionStore().new("ak-1")
    requests = [AgentRequestAny(name="sandbox_task_completion", content={"not": "a completion"})]
    async with session:
        reply = await SandboxPreHook().on_run(session, None, requests)
    assert isinstance(reply, AgentReplyText)


@pytest.mark.asyncio
async def test_hook_ingests_completion_and_injects_summary(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    session = InMemorySessionStore().new("ak-1")
    completion = _completion("t-1")
    requests = [
        AgentRequestText(prompt="original prompt"),
        AgentRequestAny(name="sandbox_task_completion", content=completion.model_dump()),
    ]
    async with session:
        _seed_task(session, "t-1")
        result = await SandboxPreHook().on_run(session, None, requests)
        registry = session.get_non_volatile_cache().get("sandbox")
    # The completion request is stripped; the summary lands in the last text request.
    assert len(result) == 1 and isinstance(result[0], AgentRequestText)
    assert result[0].prompt.startswith("original prompt")
    assert "succeeded" in result[0].prompt
    assert "task output" in result[0].prompt
    assert "default:default" in result[0].prompt
    # The task is marked consumed and terminal; the session handle is refreshed.
    assert registry["tasks"]["t-1"]["consumed"] is True
    assert registry["tasks"]["t-1"]["status"] == "succeeded"
    assert registry["sessions"]["default:default"]["sandbox_id"] == "sb-1"


@pytest.mark.asyncio
async def test_hook_second_delivery_is_deduped(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    session = InMemorySessionStore().new("ak-1")
    completion = _completion("t-1")
    async with session:
        _seed_task(session, "t-1")
        first = await SandboxPreHook().on_run(session, None, [AgentRequestAny(name="sandbox_task_completion", content=completion.model_dump())])
        second = await SandboxPreHook().on_run(session, None, [AgentRequestAny(name="sandbox_task_completion", content=completion.model_dump())])
    assert isinstance(first, list)  # first delivery proceeds into the agent turn
    assert isinstance(second, AgentReplyText)  # re-delivery halts as a no-op


@pytest.mark.asyncio
async def test_hook_completion_without_text_appends_text(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    session = InMemorySessionStore().new("ak-1")
    async with session:
        _seed_task(session, "t-1")
        result = await SandboxPreHook().on_run(
            session, None, [AgentRequestAny(name="sandbox_task_completion", content=_completion("t-1").model_dump())]
        )
    assert len(result) == 1 and isinstance(result[0], AgentRequestText)
    assert "task output" in result[0].prompt


@pytest.mark.asyncio
async def test_hook_summary_truncates_output(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg(tool_output_max_chars=5))
    session = InMemorySessionStore().new("ak-1")
    async with session:
        _seed_task(session, "t-1")
        result = await SandboxPreHook().on_run(
            session, None, [AgentRequestAny(name="sandbox_task_completion", content=_completion("t-1", stdout="0123456789").model_dump())]
        )
    assert "01234" in result[0].prompt
    assert "0123456789" not in result[0].prompt


@pytest.mark.asyncio
async def test_hook_result_ref_reported_when_offloaded(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    session = InMemorySessionStore().new("ak-1")
    completion = _completion("t-1", stdout="", result_ref={"bucket": "b", "key": "sandbox/t-1/result"})
    async with session:
        _seed_task(session, "t-1")
        result = await SandboxPreHook().on_run(session, None, [AgentRequestAny(name="sandbox_task_completion", content=completion.model_dump())])
    assert "sandbox/t-1/result" in result[0].prompt


def test_runtime_system_pre_hooks_include_sandbox(monkeypatch):
    """The third system pre-hook slot is wired: disabled config yields the no-op sandbox hook."""
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    Runtime._system_pre_hooks = None
    try:
        hooks = Runtime._get_system_pre_hooks()
        assert len(hooks) == 3
        assert isinstance(hooks[2], NoOpSandboxPreHook)
    finally:
        Runtime._system_pre_hooks = None
