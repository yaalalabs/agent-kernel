"""Tests for the sandbox capability core: data types, error hierarchy, config, the provider
ABC/contract, the manager + factory + embedded broker end-to-end, and the agent surface
(system tools + task-completion pre-hook).

Broker-flavor mechanics (thread/sqs) and the concrete providers are covered by later
iterations in test_sandbox_broker.py / test_sandbox_providers.py.
"""

import json
import sys
import types

import pytest
from pydantic import BaseModel, ValidationError

from agentkernel.core.base import Agent, Runner, Session
from agentkernel.core.config import (
    AKConfig,
    _ExecutionBrokerConfig,
    _GuardrailConfig,
    _SandboxConfig,
    _SandboxDaytonaConfig,
    _SandboxDockerConfig,
    _SandboxE2BConfig,
    _SandboxEC2SSMConfig,
    _SandboxIdentityConfig,
    _SandboxKubernetesConfig,
    _SandboxLocalSubprocessConfig,
    _SandboxPolicyConfig,
    _SandboxProfileConfig,
)
from agentkernel.core.model import AgentReplyText, AgentRequestAny, AgentRequestText
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.tool import SystemToolFactory
from agentkernel.sandbox import errors
from agentkernel.sandbox.base import Sandbox
from agentkernel.sandbox.broker.base import ExecutionCompletion
from agentkernel.sandbox.errors import SandboxCapabilityError, SandboxConfigError, SandboxPolicyError, SandboxSessionNotFoundError
from agentkernel.sandbox.factory import SandboxProviderFactory
from agentkernel.sandbox.hooks import NoOpSandboxPreHook, SandboxPreHook, SandboxPreHookFactory
from agentkernel.sandbox.manager import ExecutionManager
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
from agentkernel.sandbox.testing import FakeSandbox, FakeSandboxProvider, SandboxProviderContract
from agentkernel.sandbox.tools import (
    check_sandbox_task,
    destroy_sandbox_session,
    get_sandbox_tools,
    list_sandbox_sessions,
    new_sandbox_session,
    read_sandbox_file,
    run_code,
    run_command,
    write_sandbox_file,
)


@pytest.fixture(autouse=True)
def reset_config_singleton():
    AKConfig._reset()
    ExecutionManager._reset()
    SandboxProviderFactory._reset()
    Runtime._system_pre_hooks = None  # rebuilt from each test's mocked config
    Runtime._system_post_hooks = None
    yield
    AKConfig._reset()
    ExecutionManager._reset()
    SandboxProviderFactory._reset()
    Runtime._system_pre_hooks = None
    Runtime._system_post_hooks = None


FAKE_DOTTED = "agentkernel.sandbox.testing.FakeSandboxProvider"


class _SandboxRunner(Runner):
    """Runner whose turn runs code in the sandbox — used to exercise the real Runtime.run path."""

    async def run(self, agent, session, requests):
        code = requests[0].prompt if requests and isinstance(requests[0], AgentRequestText) else "print(1)"
        result = await ExecutionManager.get().execute(code=code)
        return AgentReplyText(response=result.stdout)

    async def stream(self, agent, session, requests):
        raise NotImplementedError()
        yield


class _SandboxAgent(Agent):
    def __init__(self, name="coder"):
        super().__init__(name, _SandboxRunner("SandboxRunner"))
        self._name = name

    @property
    def name(self):
        return self._name

    @property
    def runner(self):
        return self._runner

    def get_a2a_card(self):
        return None

    def get_description(self):
        return "sandbox test agent"

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


def _install_sandbox_cfg(monkeypatch, sandbox_cfg):
    """Point AKConfig.get() at a stub carrying the sections the runtime hook chain reads."""

    class _Cfg:
        sandbox = sandbox_cfg
        multimodal = None  # read by SystemToolFactory.get_all() alongside the sandbox block
        guardrail = _GuardrailConfig()  # read by the input/output guardrail system hooks (disabled)

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))


def _sandbox_cfg(profiles=None, **overrides):
    if profiles is None:
        profiles = {"default": _SandboxProfileConfig(type=FAKE_DOTTED, scope="per_session")}
    return _SandboxConfig(enabled=True, broker=_ExecutionBrokerConfig(flavor="embedded"), profiles=profiles, **overrides)


# --------------------------------------------------------------------------- #
# Data types (model.py)
# --------------------------------------------------------------------------- #


def test_model_package_public_exports():
    """agentkernel.sandbox imports cleanly and exposes the data types + errors module."""
    import agentkernel.sandbox as sandbox

    assert sandbox.SandboxResult is SandboxResult
    assert sandbox.IsolationTier is IsolationTier
    assert sandbox.errors.SandboxError is errors.SandboxError
    # the attached-environment surface is public: handle base + provider base
    assert issubclass(sandbox.AttachedEnvironment, sandbox.Sandbox)
    assert issubclass(sandbox.AttachedEnvironmentProvider, sandbox.SandboxProvider)


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
        caps.attaches_external,
        caps.principal_user,
        caps.policy_network,
        caps.policy_filesystem,
        caps.policy_resources,
    ):
        assert flag is False
    assert caps.provisions is True  # providers create managed sandboxes unless declared attach-only


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
        errors.ExecutionBrokerError,
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
    assert ExecutionManager.get() is None


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


def test_factory_builtin_docker_missing_extra_raises_import_error(monkeypatch):
    """docker is a real-import branch (#541); a missing SDK gets the friendly extra message."""
    cfg = _sandbox_cfg(profiles={"default": _SandboxProfileConfig(type="docker", docker=_SandboxDockerConfig())})
    _install_sandbox_cfg(monkeypatch, cfg)
    monkeypatch.delitem(sys.modules, "agentkernel.sandbox.providers.docker", raising=False)
    monkeypatch.setitem(sys.modules, "docker", None)  # simulate the docker SDK not being installed
    with pytest.raises(ImportError) as exc_info:
        SandboxProviderFactory.get("default")
    assert "agentkernel[sandbox-docker]" in str(exc_info.value)


def test_factory_builtin_docker_real_import(monkeypatch):
    cfg = _sandbox_cfg(profiles={"default": _SandboxProfileConfig(type="docker", docker=_SandboxDockerConfig())})
    _install_sandbox_cfg(monkeypatch, cfg)
    fake_sdk = types.SimpleNamespace(errors=types.SimpleNamespace(NotFound=type("NotFound", (Exception,), {})), from_env=lambda: None)
    monkeypatch.delitem(sys.modules, "agentkernel.sandbox.providers.docker", raising=False)
    monkeypatch.setitem(sys.modules, "docker", fake_sdk)
    provider = SandboxProviderFactory.get("default")
    assert type(provider).__name__ == "DockerSandboxProvider"


def test_factory_builtin_local_subprocess_real_import(monkeypatch):
    cfg = _sandbox_cfg(profiles={"default": _SandboxProfileConfig(type="local_subprocess", local_subprocess=_SandboxLocalSubprocessConfig())})
    _install_sandbox_cfg(monkeypatch, cfg)
    provider = SandboxProviderFactory.get("default")
    from agentkernel.sandbox.providers.local_subprocess import LocalSubprocessSandboxProvider

    assert isinstance(provider, LocalSubprocessSandboxProvider)


def test_factory_unknown_short_name_raises_listing_builtins(monkeypatch):
    """A short name with no landed if/elif branch (e.g. a provider from a future iteration)
    is an unknown type: fail loud, naming the available built-ins (#541 shape)."""
    cfg = _sandbox_cfg(profiles={"default": _SandboxProfileConfig(type="kubernetes", kubernetes=_SandboxKubernetesConfig())})
    _install_sandbox_cfg(monkeypatch, cfg)
    with pytest.raises(SandboxConfigError) as exc_info:
        SandboxProviderFactory.get("default")
    assert "local_subprocess" in str(exc_info.value) and "docker" in str(exc_info.value)


def test_factory_builtin_ec2_ssm_real_import(monkeypatch):
    cfg = _sandbox_cfg(
        profiles={"default": _SandboxProfileConfig(type="ec2_ssm", environment="attached", ec2_ssm=_SandboxEC2SSMConfig(attach_to="i-1"))}
    )
    _install_sandbox_cfg(monkeypatch, cfg)
    provider = SandboxProviderFactory.get("default")
    assert type(provider).__name__ == "EC2SSMSandboxProvider"


def test_factory_ec2_ssm_managed_mode_fails_closed(monkeypatch):
    """An attach-only provider under the default managed mode is rejected at build time."""
    cfg = _sandbox_cfg(profiles={"default": _SandboxProfileConfig(type="ec2_ssm", ec2_ssm=_SandboxEC2SSMConfig(attach_to="i-1"))})
    _install_sandbox_cfg(monkeypatch, cfg)
    with pytest.raises(SandboxConfigError) as exc_info:
        SandboxProviderFactory.get("default")
    assert "attach-only" in str(exc_info.value) and "environment: attached" in str(exc_info.value)


def test_factory_builtin_ec2_ssm_missing_extra_raises_import_error(monkeypatch):
    cfg = _sandbox_cfg(profiles={"default": _SandboxProfileConfig(type="ec2_ssm", ec2_ssm=_SandboxEC2SSMConfig())})
    _install_sandbox_cfg(monkeypatch, cfg)
    monkeypatch.delitem(sys.modules, "agentkernel.sandbox.providers.ec2_ssm", raising=False)
    monkeypatch.setitem(sys.modules, "boto3", None)  # simulate boto3 not being installed
    with pytest.raises(ImportError) as exc_info:
        SandboxProviderFactory.get("default")
    assert "agentkernel[aws]" in str(exc_info.value)


def test_factory_builtin_e2b_missing_extra_raises_import_error(monkeypatch):
    """The e2b SDK is not a dev dependency, so the real-import branch naturally exercises
    the missing-extra path here; the provider itself is covered against a fake SDK in
    test_sandbox_providers.py."""
    cfg = _sandbox_cfg(profiles={"default": _SandboxProfileConfig(type="e2b", e2b=_SandboxE2BConfig())})
    _install_sandbox_cfg(monkeypatch, cfg)
    monkeypatch.delitem(sys.modules, "agentkernel.sandbox.providers.e2b", raising=False)
    monkeypatch.setitem(sys.modules, "e2b_code_interpreter", None)
    monkeypatch.setitem(sys.modules, "e2b", None)
    with pytest.raises(ImportError) as exc_info:
        SandboxProviderFactory.get("default")
    assert "agentkernel[e2b]" in str(exc_info.value)


def test_factory_builtin_daytona_missing_extra_raises_import_error(monkeypatch):
    cfg = _sandbox_cfg(profiles={"default": _SandboxProfileConfig(type="daytona", daytona=_SandboxDaytonaConfig())})
    _install_sandbox_cfg(monkeypatch, cfg)
    monkeypatch.delitem(sys.modules, "agentkernel.sandbox.providers.daytona", raising=False)
    monkeypatch.setitem(sys.modules, "daytona", None)
    with pytest.raises(ImportError) as exc_info:
        SandboxProviderFactory.get("default")
    assert "agentkernel[daytona]" in str(exc_info.value)


def test_factory_builtin_missing_config_block_raises(monkeypatch):
    cfg = _sandbox_cfg(profiles={"default": _SandboxProfileConfig(type="docker")})  # no docker block
    _install_sandbox_cfg(monkeypatch, cfg)
    with pytest.raises(SandboxConfigError):
        SandboxProviderFactory.get("default")


def test_manager_build_resolver_custom_and_invalid():
    resolver = ExecutionManager._build_resolver(_sandbox_cfg(principal_resolver="agentkernel.sandbox.principal.AgentPrincipalResolver"))
    assert isinstance(resolver, AgentPrincipalResolver)
    with pytest.raises(SandboxConfigError):
        ExecutionManager._build_resolver(_sandbox_cfg(principal_resolver="agentkernel.sandbox.model.SandboxResult"))


# --------------------------------------------------------------------------- #
# ExecutionManager end-to-end via the embedded broker (manager.py / broker/*)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_manager_execute_code_and_command(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    mgr = ExecutionManager.get()
    session = InMemorySessionStore().new("ak-1")
    async with session:
        code_result = await mgr.execute(code="print('hi')")
        cmd_result = await mgr.execute(command="echo hi")
    assert code_result.exit_code == 0 and code_result.stdout == "print('hi')"
    assert cmd_result.exit_code == 0 and cmd_result.stdout == "echo hi"
    assert code_result.sandbox_session_id == "default:default"


@pytest.mark.asyncio
async def test_manager_session_round_trip_and_reuse(monkeypatch):
    """Drive two real Runtime.run turns (each clears the volatile cache in finally and stores
    the session): the sandbox session must persist via nv_cache and be reused, not recreated."""
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    store = InMemorySessionStore()
    runtime = Runtime(store)
    agent = _SandboxAgent()

    r1 = await runtime.run(agent, store.new("ak-1"), [AgentRequestText(prompt="print(1)")])
    # Reload the session from the store between turns (exercises the nv_cache round-trip).
    r2 = await runtime.run(agent, store.load("ak-1"), [AgentRequestText(prompt="print(2)")])

    provider = SandboxProviderFactory.get("default")
    assert len(provider.created_ids) == 1  # reused across turns, not recreated
    assert r1.response == "print(1)" and r2.response == "print(2)"


@pytest.mark.asyncio
async def test_manager_unknown_session_id_raises(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    mgr = ExecutionManager.get()
    session = InMemorySessionStore().new("ak-1")
    async with session:
        with pytest.raises(SandboxSessionNotFoundError):
            await mgr.execute(code="print(1)", sandbox_session_id="does-not-exist")


@pytest.mark.asyncio
async def test_manager_cross_session_isolation(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    mgr = ExecutionManager.get()
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
    mgr = ExecutionManager.get()
    provider = SandboxProviderFactory.get("default")
    session = InMemorySessionStore().new("ak-1")
    async with session:
        first = await mgr.execute(code="print(1)")
        vanished = provider.created_ids[0]
        provider._sandboxes.pop(vanished)  # simulate the backend sandbox disappearing
        healed = await mgr.execute(code="print(2)")  # attach -> SandboxGoneError -> recreate
    assert len(provider.created_ids) == 2
    assert provider.created_ids[0] != provider.created_ids[1]
    # Recreated under the SAME sandbox_session_id (self-heal, not a new session).
    assert healed.sandbox_session_id == first.sandbox_session_id
    # The silent recreation is surfaced to the caller, never hidden.
    assert first.notice is None
    assert "recreated empty" in healed.notice


@pytest.mark.asyncio
async def test_manager_idle_timeout_recreates_on_touch(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    mgr = ExecutionManager.get()
    provider = SandboxProviderFactory.get("default")
    session = InMemorySessionStore().new("ak-1")
    async with session:
        await mgr.execute(code="print(1)")
        first_id = provider.created_ids[0]
        # backdate last_used_at so the next touch treats the session as idle-expired
        registry = session.get_non_volatile_cache().get("sandbox")
        registry["sessions"]["default:default"]["last_used_at"] = 0.0
        reset = await mgr.execute(code="print(2)")
    assert len(provider.created_ids) == 2
    assert first_id in provider.destroyed_ids
    # The idle reset is surfaced to the caller, never hidden.
    assert "idle" in reset.notice and "discarded" in reset.notice


@pytest.mark.asyncio
async def test_tool_result_carries_idle_reset_notice(monkeypatch):
    """The recreation notice reaches the agent through the tool JSON contract."""
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    session = InMemorySessionStore().new("ak-1")
    async with session:
        clean = json.loads(await run_code("print(1)"))
        assert "notice" not in clean
        registry = session.get_non_volatile_cache().get("sandbox")
        registry["sessions"]["default:default"]["last_used_at"] = 0.0
        reset = json.loads(await run_code("print(2)"))
    assert "idle" in reset["notice"]


@pytest.mark.asyncio
async def test_manager_per_call_scope_creates_and_destroys(monkeypatch):
    profile = _SandboxProfileConfig(type=FAKE_DOTTED, scope="per_call")
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg(profiles={"default": profile}))
    mgr = ExecutionManager.get()
    provider = SandboxProviderFactory.get("default")
    session = InMemorySessionStore().new("ak-1")
    async with session:
        await mgr.execute(code="print(1)")
        await mgr.execute(code="print(2)")
    assert len(provider.created_ids) == 2  # fresh per call
    assert len(provider.destroyed_ids) == 2  # each torn down


@pytest.mark.asyncio
async def test_manager_per_call_destroys_in_finally_on_failure(monkeypatch):
    """per_call teardown is in `finally`: an execution that raises still disposes the ephemeral
    sandbox (and the exception propagates)."""
    profile = _SandboxProfileConfig(type=FAKE_DOTTED, scope="per_call")
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg(profiles={"default": profile}))
    mgr = ExecutionManager.get()
    provider = SandboxProviderFactory.get("default")

    async def boom(self, code, language="python", timeout=None):
        raise RuntimeError("execution blew up")

    monkeypatch.setattr("agentkernel.sandbox.testing.FakeSandbox.execute_code", boom)
    session = InMemorySessionStore().new("ak-1")
    async with session:
        with pytest.raises(RuntimeError):
            await mgr.execute(code="print(1)")
    assert len(provider.created_ids) == 1
    assert provider.created_ids[0] in provider.destroyed_ids  # torn down despite the failure


@pytest.mark.asyncio
async def test_manager_explicit_session_uses_its_own_profile(monkeypatch):
    """Blocker regression: an explicit sandbox_session_id resolves under the profile it was
    minted with, not the caller's/default — never rerouting to another provider."""
    default_profile = _SandboxProfileConfig(type=FAKE_DOTTED, scope="per_session")
    other_profile = _SandboxProfileConfig(type=FAKE_DOTTED, scope="per_session")
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg(profiles={"default": default_profile, "gpu": other_profile}))
    mgr = ExecutionManager.get()
    session = InMemorySessionStore().new("ak-1")
    async with session:
        minted = mgr.new_session(profile="gpu")
        # profile omitted → must still resolve under 'gpu', not default_profile
        result = await mgr.execute(code="print(1)", sandbox_session_id=minted.sandbox_session_id)
        assert result.sandbox_session_id == minted.sandbox_session_id
        stored = mgr.list_sessions()
        assert next(s for s in stored if s.sandbox_session_id == minted.sandbox_session_id).profile == "gpu"
        # a contradicting explicit profile is rejected, not silently rerouted
        with pytest.raises(SandboxConfigError):
            await mgr.execute(code="print(2)", sandbox_session_id=minted.sandbox_session_id, profile="default")


@pytest.mark.asyncio
async def test_manager_per_runtime_shared_across_ak_sessions(monkeypatch):
    # per_runtime maps to exactly one shared sandbox session per profile, in process memory,
    # reused across distinct AK sessions (no pooling in v1).
    profile = _SandboxProfileConfig(type=FAKE_DOTTED, scope="per_runtime")
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg(profiles={"default": profile}))
    mgr = ExecutionManager.get()
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
    mgr = ExecutionManager.get()
    session = InMemorySessionStore().new("ak-1")
    async with session:
        await mgr.upload("data.txt", b"hello")
        content = await mgr.download("data.txt")
    assert content == b"hello"


@pytest.mark.asyncio
async def test_manager_destroy_session(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    mgr = ExecutionManager.get()
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
    mgr = ExecutionManager.get()
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
    mgr = ExecutionManager.get()
    session = InMemorySessionStore().new("ak-1")
    async with session:
        with pytest.raises(SandboxPolicyError):
            await mgr.execute(code="print(1)")


@pytest.mark.asyncio
async def test_fail_closed_policy_strict(monkeypatch):
    profile = _SandboxProfileConfig(type=FAKE_DOTTED, policy=_SandboxPolicyConfig(network_egress="deny", strict=True))
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg(profiles={"default": profile}))
    mgr = ExecutionManager.get()
    session = InMemorySessionStore().new("ak-1")
    async with session:
        with pytest.raises(SandboxPolicyError):
            await mgr.execute(code="print(1)")


@pytest.mark.asyncio
async def test_policy_non_strict_proceeds_with_warning(monkeypatch, caplog):
    profile = _SandboxProfileConfig(type=FAKE_DOTTED, policy=_SandboxPolicyConfig(network_egress="deny", strict=False))
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg(profiles={"default": profile}))
    mgr = ExecutionManager.get()
    session = InMemorySessionStore().new("ak-1")
    with caplog.at_level("WARNING", logger="ak.sandbox.broker"):
        async with session:
            r1 = await mgr.execute(code="print(1)")
            r2 = await mgr.execute(code="print(2)")
    assert r1.exit_code == 0 and r2.exit_code == 0
    # Proceeds with exactly one policy-mismatch warning across the two calls (process-lifetime memo).
    mismatch_warnings = [r for r in caplog.records if "cannot enforce policy dimensions" in r.message]
    assert len(mismatch_warnings) == 1


# --------------------------------------------------------------------------- #
# System tools (tools.py) — iteration 4
# --------------------------------------------------------------------------- #

SANDBOX_TOOL_NAMES = [
    "run_code",
    "run_command",
    "write_sandbox_file",
    "read_sandbox_file",
    "check_sandbox_task",
    "list_sandbox_sessions",
    "new_sandbox_session",
    "destroy_sandbox_session",
]


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
    assert "[Sandbox execution]" in guidance
    assert "'default' (default)" in guidance
    assert FAKE_DOTTED in guidance
    assert "per_session" in guidance
    assert "1234" in guidance


def test_tool_guidance_flags_attached_and_no_persistent_shell(monkeypatch):
    """An ec2_ssm attached profile is annotated in the injected guidance so the agent knows
    the environment is a pre-existing system with no persistent shell across commands."""
    profile = _SandboxProfileConfig(type="ec2_ssm", environment="attached", ec2_ssm=_SandboxEC2SSMConfig(attach_to="i-1"))
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg(profiles={"ec2": profile}, default_profile="ec2"))
    guidance = get_sandbox_tools()[0].description
    assert "environment attached" in guidance
    assert "NO persistent shell" in guidance
    assert "cd /app && ./run.sh" in guidance


def test_system_prompt_suffix_carries_sandbox_guidance(monkeypatch):
    """The capability is self-describing: the whole sandbox section lands in the system-prompt
    suffix (rendered coherently — the empty per-tool descriptions leave no blank lines)."""
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    suffix = SystemToolFactory.get_system_prompt_suffix()
    assert "[Sandbox execution]" in suffix
    assert "run_code" in suffix and "check_sandbox_task" in suffix
    assert "new_sandbox_session" in suffix and "destroy_sandbox_session" in suffix
    assert "list_sandbox_sessions" in suffix
    assert "never invent one" in suffix
    assert '"notice"' in suffix
    assert "sandbox_session_id" in suffix
    assert "" not in suffix.splitlines()

    _install_sandbox_cfg(monkeypatch, _SandboxConfig(enabled=False))
    assert SystemToolFactory.get_system_prompt_suffix() == ""


def test_agent_setup_system_prompt_injects_sandbox_guidance(monkeypatch):
    """Agent._setup_system_prompt() (called by every framework adapter at wrap time) hands
    the sandbox guidance to override_system_prompt — agent authors never describe the tools."""
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    captured = []

    class _Probe:
        name = "coder"

        def override_system_prompt(self, prompt):
            captured.append(prompt)

    from agentkernel.core.base import Agent

    Agent._setup_system_prompt(_Probe())
    assert "[Sandbox execution]" in captured[0]


def test_agents_list_restricts_tools_and_prompt(monkeypatch):
    """sandbox.agents limits tool attachment and prompt injection to the named agents;
    anonymous callers (no agent context) are not filtered."""
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg(agents=["coder"]))
    assert [t.name for t in SystemToolFactory.get_all("coder")] == SANDBOX_TOOL_NAMES
    assert SystemToolFactory.get_all("triage") == []
    assert [t.name for t in SystemToolFactory.get_all()] == SANDBOX_TOOL_NAMES  # anonymous: unfiltered

    assert "[Sandbox execution]" in SystemToolFactory.get_system_prompt_suffix("coder")
    assert SystemToolFactory.get_system_prompt_suffix("triage") == ""


def test_agents_list_absent_keeps_all_agents(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    assert [t.name for t in SystemToolFactory.get_all("anyone")] == SANDBOX_TOOL_NAMES


def test_agents_list_filters_multimodal_independently(monkeypatch):
    """Each capability carries its own agents list; sandbox and multimodal filter independently."""

    class _MM:
        enabled = True
        agents = ["vision"]

    class _Cfg:
        sandbox = _sandbox_cfg(agents=["coder"])
        multimodal = _MM

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
    assert [t.name for t in SystemToolFactory.get_all("vision")] == ["analyze_attachments"]
    assert [t.name for t in SystemToolFactory.get_all("coder")] == SANDBOX_TOOL_NAMES
    assert SystemToolFactory.get_all("other") == []


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
async def test_file_tools_against_non_files_provider_return_capability_error(monkeypatch):
    """A file tool against a profile whose provider lacks `files` returns the capability-error
    string, like any other unsupported operation."""
    no_files = FakeSandboxProvider.capabilities.model_copy(update={"files": False})
    monkeypatch.setattr(FakeSandboxProvider, "capabilities", no_files)
    # A no-files provider's sandbox doesn't override the file ops, so the base ABC raises
    # SandboxCapabilityError — restore that behavior on the fake (which normally overrides them).
    monkeypatch.setattr(FakeSandbox, "upload_file", Sandbox.upload_file)
    monkeypatch.setattr(FakeSandbox, "download_file", Sandbox.download_file)
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    session = InMemorySessionStore().new("ak-1")
    async with session:
        write_payload = json.loads(await write_sandbox_file("f.txt", "hi"))
        read_payload = json.loads(await read_sandbox_file("f.txt"))
    assert "files" in write_payload["error"]
    assert "files" in read_payload["error"]


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


@pytest.mark.asyncio
async def test_tool_new_session_mints_isolated_environment(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    session = InMemorySessionStore().new("ak-1")
    async with session:
        await run_code("print(1)")  # default session gets its own backend sandbox
        minted = json.loads(await new_sandbox_session())
        assert minted["profile"] == "default"
        fresh_id = minted["sandbox_session_id"]
        assert fresh_id != "default:default"
        result = json.loads(await run_code("print(2)", sandbox_session_id=fresh_id))
        assert result["sandbox_session_id"] == fresh_id
    provider = SandboxProviderFactory.get("default")
    assert len(provider.created_ids) == 2  # the minted session is a separate environment


@pytest.mark.asyncio
async def test_tool_new_session_rejects_non_per_session_scope(monkeypatch):
    profile = _SandboxProfileConfig(type=FAKE_DOTTED, scope="per_runtime")
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg(profiles={"default": profile}))
    session = InMemorySessionStore().new("ak-1")
    async with session:
        payload = json.loads(await new_sandbox_session())
    assert "per_runtime" in payload["error"]


@pytest.mark.asyncio
async def test_tool_destroy_session_resets_default(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    session = InMemorySessionStore().new("ak-1")
    async with session:
        await run_code("print(1)")
        provider = SandboxProviderFactory.get("default")
        first_backend = provider.created_ids[0]
        destroyed = json.loads(await destroy_sandbox_session("default:default"))
        assert destroyed == {"sandbox_session_id": "default:default", "destroyed": True}
        assert first_backend in provider.destroyed_ids
        json.loads(await destroy_sandbox_session("default:default"))  # idempotent
        await run_code("print(2)")  # the next default call starts clean
        assert len(provider.created_ids) == 2


def test_manager_new_session_unknown_profile(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    mgr = ExecutionManager.get()
    with pytest.raises(SandboxConfigError):
        mgr.new_session("no-such-profile")


@pytest.mark.asyncio
async def test_tool_list_sessions_shows_names_and_shrinks_on_destroy(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg())
    session = InMemorySessionStore().new("ak-1")
    async with session:
        await run_code("print(1)")  # default session
        minted = json.loads(await new_sandbox_session(name="uv-project"))
        assert minted["name"] == "uv-project"

        listing = json.loads(await list_sandbox_sessions())["sessions"]
        by_id = {s["sandbox_session_id"]: s for s in listing}
        assert set(by_id) == {"default:default", minted["sandbox_session_id"]}
        assert by_id[minted["sandbox_session_id"]]["name"] == "uv-project"
        assert by_id["default:default"]["name"] is None
        assert by_id["default:default"]["profile"] == "default"

        await destroy_sandbox_session(minted["sandbox_session_id"])
        remaining = json.loads(await list_sandbox_sessions())["sessions"]
        assert [s["sandbox_session_id"] for s in remaining] == ["default:default"]


# --------------------------------------------------------------------------- #
# Task-completion ingestion (hooks.py) — iteration 4
# --------------------------------------------------------------------------- #


def _completion(task_id, sandbox_session_id="default:default", status="succeeded", stdout="task output", **kwargs):
    return ExecutionCompletion(
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


# --------------------------------------------------------------------------- #
# Environment lifecycle: managed vs attached (factory validation + worker rules)
# --------------------------------------------------------------------------- #

ATTACHING_CAPS = SandboxCapabilities(
    isolation=IsolationTier.NONE,
    shell=True,
    languages=["python", "bash"],
    files=True,
    stateful=True,
    attach=True,
    attaches_external=True,
)


def test_environment_mode_validates_and_defaults():
    assert _SandboxProfileConfig(type=FAKE_DOTTED).environment == "managed"
    with pytest.raises(ValidationError):
        _SandboxProfileConfig(type=FAKE_DOTTED, environment="isolated")
    # single-backend sugar passes the mode onto the synthesized profile
    cfg = _SandboxConfig(enabled=True, type=FAKE_DOTTED, environment="attached")
    assert cfg.profiles["default"].environment == "attached"


def test_factory_attached_requires_attaches_external(monkeypatch):
    """attached + a provider that can only provision managed sandboxes -> fail at build time."""
    profile = _SandboxProfileConfig(type=FAKE_DOTTED, environment="attached", params={"attach_to": "target-1"})
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg(profiles={"default": profile}))
    with pytest.raises(SandboxConfigError) as exc_info:
        SandboxProviderFactory.get("default")
    assert "cannot attach to an existing environment" in str(exc_info.value)


def test_factory_attached_requires_attach_to(monkeypatch):
    monkeypatch.setattr(FakeSandboxProvider, "capabilities", ATTACHING_CAPS)
    profile = _SandboxProfileConfig(type=FAKE_DOTTED, environment="attached")  # no attach_to
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg(profiles={"default": profile}))
    with pytest.raises(SandboxConfigError) as exc_info:
        SandboxProviderFactory.get("default")
    assert "no attach_to target" in str(exc_info.value)


def test_factory_attached_resolves_with_target(monkeypatch):
    monkeypatch.setattr(FakeSandboxProvider, "capabilities", ATTACHING_CAPS)
    profile = _SandboxProfileConfig(type=FAKE_DOTTED, environment="attached", params={"attach_to": "target-1"})
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg(profiles={"default": profile}))
    assert isinstance(SandboxProviderFactory.get("default"), FakeSandboxProvider)


def test_factory_managed_rejects_attach_to(monkeypatch):
    """attach_to under the default managed mode is rejected: connecting to an existing
    environment must be a deliberate choice, never a side effect."""
    profile = _SandboxProfileConfig(type=FAKE_DOTTED, params={"attach_to": "target-1"})
    _install_sandbox_cfg(monkeypatch, _sandbox_cfg(profiles={"default": profile}))
    with pytest.raises(SandboxConfigError) as exc_info:
        SandboxProviderFactory.get("default")
    assert "environment: attached" in str(exc_info.value)


def _attached_fake_cfg(monkeypatch):
    monkeypatch.setattr(FakeSandboxProvider, "capabilities", ATTACHING_CAPS)
    profile = _SandboxProfileConfig(type=FAKE_DOTTED, environment="attached", params={"attach_to": "target-1"})
    return _sandbox_cfg(profiles={"default": profile})


@pytest.mark.asyncio
async def test_worker_attached_destroy_drops_binding_without_disposing(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _attached_fake_cfg(monkeypatch))
    mgr = ExecutionManager.get()
    session = InMemorySessionStore().new("s-attached")
    async with session:
        result = await mgr.execute(code="print('hi')")
        provider = SandboxProviderFactory.get("default")
        assert provider.created_ids  # bound to a live handle
        await mgr.destroy_session(result.sandbox_session_id)
        assert provider.destroyed_ids == []  # binding dropped, environment untouched


@pytest.mark.asyncio
async def test_worker_attached_gone_is_not_recreated(monkeypatch):
    _install_sandbox_cfg(monkeypatch, _attached_fake_cfg(monkeypatch))
    mgr = ExecutionManager.get()
    session = InMemorySessionStore().new("s-attached-gone")
    async with session:
        await mgr.execute(code="print('hi')")
        provider = SandboxProviderFactory.get("default")
        assert len(provider.created_ids) == 1
        provider._sandboxes.clear()  # the attached environment vanishes
        with pytest.raises(errors.SandboxGoneError) as exc_info:
            await mgr.execute(code="print('again')")
        assert "not recreating" in str(exc_info.value)
        assert len(provider.created_ids) == 1  # self-heal never provisioned a replacement
