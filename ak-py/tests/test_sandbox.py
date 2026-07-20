"""Iteration 1 tests for the sandbox capability: data types, error hierarchy, and config.

Broader behavior (providers, broker, tools, hooks) is covered by later iterations in
test_sandbox_broker.py / test_sandbox_providers.py.
"""

import pytest
from pydantic import ValidationError

from agentkernel.core.base import Session
from agentkernel.core.config import AKConfig, _SandboxConfig, _SandboxDockerConfig, _SandboxProfileConfig
from agentkernel.sandbox import errors
from agentkernel.sandbox.base import Sandbox
from agentkernel.sandbox.errors import SandboxCapabilityError
from agentkernel.sandbox.model import (
    IsolationTier,
    SandboxCapabilities,
    SandboxPolicy,
    SandboxPrincipal,
    SandboxResult,
)
from agentkernel.sandbox.principal import AgentPrincipalResolver
from agentkernel.sandbox.testing import FakeSandboxProvider, SandboxProviderContract


@pytest.fixture(autouse=True)
def reset_config_singleton():
    AKConfig._reset()
    yield
    AKConfig._reset()


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
