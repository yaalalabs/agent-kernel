"""First-party sandbox provider tests.

``local_subprocess`` runs real subprocesses (``sys.executable`` / bash) against real temp
directories, including the public ``SandboxProviderContract`` suite. ``docker`` runs
against a mocked Docker SDK (no daemon): call shapes, policy mapping arguments, and
``to_thread`` usage are asserted per spec §Testing.
"""

import asyncio
import base64
import importlib
import io
import shlex
import sys
import tarfile
import threading
import time
import types
from pathlib import Path

import pytest

from agentkernel.core.config import (
    AKConfig,
    _ExecutionBrokerConfig,
    _SandboxConfig,
    _SandboxDockerConfig,
    _SandboxIdentityConfig,
    _SandboxKubernetesConfig,
    _SandboxLocalSubprocessConfig,
    _SandboxProfileConfig,
)
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.sandbox.broker.base import ExecutionRequest
from agentkernel.sandbox.broker.worker import BrokerWorkerCore
from agentkernel.sandbox.errors import SandboxCapabilityError, SandboxGoneError, SandboxPolicyError, SandboxProvisionError, SandboxTimeoutError
from agentkernel.sandbox.factory import SandboxProviderFactory
from agentkernel.sandbox.manager import ExecutionManager
from agentkernel.sandbox.model import SandboxPolicy, SandboxPrincipal, SandboxSession
from agentkernel.sandbox.providers.local_subprocess import LocalSubprocessSandboxProvider
from agentkernel.sandbox.testing import FAIL_MARKER, SandboxProviderContract


@pytest.fixture(autouse=True)
def reset_singletons():
    AKConfig._reset()
    ExecutionManager._reset()
    SandboxProviderFactory._reset()
    yield
    AKConfig._reset()
    ExecutionManager._reset()
    SandboxProviderFactory._reset()


def _principal_policy():
    return SandboxPrincipal(subject="test-agent"), SandboxPolicy()


# --------------------------------------------------------------------------- #
# local_subprocess — real subprocesses, real temp dirs
# --------------------------------------------------------------------------- #


class TestLocalSubprocessContract(SandboxProviderContract):
    """The public provider contract, run against the real local_subprocess backend."""

    @pytest.fixture
    def provider(self):
        return LocalSubprocessSandboxProvider(_SandboxLocalSubprocessConfig())


def test_subprocess_construction_logs_no_isolation_warning(caplog):
    with caplog.at_level("WARNING", logger="ak.sandbox.provider"):
        LocalSubprocessSandboxProvider(_SandboxLocalSubprocessConfig())
    assert "NO isolation" in caplog.text


@pytest.mark.asyncio
async def test_subprocess_python_stdout_stderr_exit_code():
    provider = LocalSubprocessSandboxProvider(_SandboxLocalSubprocessConfig())
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    try:
        result = await sandbox.execute_code("import sys\nprint('out')\nprint('err', file=sys.stderr)")
        assert (result.stdout, result.stderr.strip(), result.exit_code) == ("out\n", "err", 0)
        failing = await sandbox.execute_code("import sys; sys.exit(3)")
        assert failing.exit_code == 3
    finally:
        await provider.destroy(sandbox.id)


@pytest.mark.asyncio
async def test_subprocess_bash_language_and_shell_command():
    provider = LocalSubprocessSandboxProvider(_SandboxLocalSubprocessConfig())
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    try:
        assert (await sandbox.execute_code("echo bash-code", "bash")).stdout == "bash-code\n"
        assert (await sandbox.execute_command("echo shell-cmd")).stdout == "shell-cmd\n"
    finally:
        await provider.destroy(sandbox.id)


@pytest.mark.asyncio
async def test_subprocess_timeout_kills_process_group():
    provider = LocalSubprocessSandboxProvider(_SandboxLocalSubprocessConfig())
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    try:
        started = time.monotonic()
        with pytest.raises(SandboxTimeoutError):
            await sandbox.execute_code("import time\ntime.sleep(30)", timeout=0.3)
        assert time.monotonic() - started < 5  # killed, not waited out
    finally:
        await provider.destroy(sandbox.id)


@pytest.mark.asyncio
async def test_subprocess_files_map_onto_workdir():
    provider = LocalSubprocessSandboxProvider(_SandboxLocalSubprocessConfig())
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    try:
        await sandbox.upload_file("data/notes.txt", b"hello files")
        assert await sandbox.download_file("data/notes.txt") == b"hello files"
        # The file is visible to executions (same working directory).
        result = await sandbox.execute_command("cat data/notes.txt")
        assert result.stdout == "hello files"
    finally:
        await provider.destroy(sandbox.id)


@pytest.mark.asyncio
async def test_subprocess_path_traversal_is_refused():
    provider = LocalSubprocessSandboxProvider(_SandboxLocalSubprocessConfig())
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    try:
        with pytest.raises(SandboxPolicyError):
            await sandbox.upload_file("../escape.txt", b"nope")
    finally:
        await provider.destroy(sandbox.id)


@pytest.mark.asyncio
async def test_subprocess_attach_reconnects_and_destroy_removes(tmp_path):
    provider = LocalSubprocessSandboxProvider(_SandboxLocalSubprocessConfig(workdir=str(tmp_path)))
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    assert Path(sandbox.id).is_relative_to(tmp_path)  # honors the configured base workdir
    await sandbox.upload_file("state.txt", b"persisted")

    reattached = await provider.attach(sandbox.id, principal=principal, policy=policy)
    assert await reattached.download_file("state.txt") == b"persisted"

    await provider.destroy(sandbox.id)
    assert not Path(sandbox.id).exists()
    with pytest.raises(SandboxGoneError):
        await provider.attach(sandbox.id, principal=principal, policy=policy)


@pytest.mark.asyncio
async def test_subprocess_end_to_end_through_manager(monkeypatch):
    """The full path: config -> factory real import -> manager -> embedded broker -> real
    subprocess, with workspace state persisting across manager calls (attach path)."""
    profile = _SandboxProfileConfig(type="local_subprocess", local_subprocess=_SandboxLocalSubprocessConfig())
    cfg = _SandboxConfig(enabled=True, broker=_ExecutionBrokerConfig(flavor="embedded"), profiles={"default": profile})

    class _Cfg:
        sandbox = cfg
        multimodal = None

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
    mgr = ExecutionManager.get()
    session = InMemorySessionStore().new("ak-1")
    async with session:
        result = await mgr.execute(command="echo persisted > state.txt")
        assert result.exit_code == 0
        assert await mgr.download("state.txt") == b"persisted\n"
        assert result.sandbox_session_id == "default:default"


# --------------------------------------------------------------------------- #
# docker — mocked SDK (no daemon)
# --------------------------------------------------------------------------- #


class FakeNotFound(Exception):
    pass


class FakeContainer:
    def __init__(self, container_id="c-1"):
        self.id = container_id
        self.status = "running"
        self.exec_calls = []
        self.exec_threads = []
        self.files: dict[str, bytes] = {}
        self.removed = False
        self.started = False
        self.exec_delay = 0.0

    def exec_run(self, cmd, workdir=None, demux=True):
        self.exec_calls.append((list(cmd), workdir))
        self.exec_threads.append(threading.current_thread())
        if self.exec_delay:
            time.sleep(self.exec_delay)
        return types.SimpleNamespace(exit_code=0, output=(b"fake stdout", b""))

    def put_archive(self, path, data):
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            for member in tar.getmembers():
                if member.isfile():
                    self.files[f"{path}/{member.name}"] = tar.extractfile(member).read()
        return True

    def get_archive(self, path):
        if path not in self.files:
            raise FakeNotFound(path)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo(name=path.rsplit("/", 1)[-1])
            info.size = len(self.files[path])
            tar.addfile(info, io.BytesIO(self.files[path]))
        return iter([buf.getvalue()]), {}

    def remove(self, force=False):
        self.removed = True

    def start(self):
        self.started = True
        self.status = "running"


class FakeContainersAPI:
    def __init__(self):
        self.run_calls = []
        self.by_id: dict[str, FakeContainer] = {}

    def run(self, image, **kwargs):
        self.run_calls.append((image, kwargs))
        container = FakeContainer(f"c-{len(self.run_calls)}")
        self.by_id[container.id] = container
        return container

    def get(self, container_id):
        if container_id not in self.by_id:
            raise FakeNotFound(container_id)
        return self.by_id[container_id]


@pytest.fixture
def docker_env(monkeypatch):
    """Import the provider module against a fake docker SDK and return (module, client)."""
    client = types.SimpleNamespace(containers=FakeContainersAPI())
    fake_sdk = types.SimpleNamespace(errors=types.SimpleNamespace(NotFound=FakeNotFound), from_env=lambda: client)
    monkeypatch.setitem(sys.modules, "docker", fake_sdk)
    module = importlib.import_module("agentkernel.sandbox.providers.docker")
    monkeypatch.setattr(module, "docker", fake_sdk)  # rebind in case it was imported earlier
    return module, client


def _docker_provider(module, config=None):
    return module.DockerSandboxProvider(config or _SandboxDockerConfig())


@pytest.mark.asyncio
async def test_docker_create_call_shape(docker_env):
    module, client = docker_env
    provider = _docker_provider(module, _SandboxDockerConfig(image="custom:1"))
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    image, kwargs = client.containers.run_calls[0]
    assert image == "custom:1"
    assert kwargs["command"] == ["sleep", "infinity"]
    assert kwargs["detach"] is True
    assert kwargs["working_dir"] == "/workspace"
    assert "network_mode" not in kwargs and "runtime" not in kwargs  # defaults map to nothing
    assert sandbox.id == client.containers.by_id[sandbox.id].id


@pytest.mark.asyncio
async def test_docker_policy_mapping_arguments(docker_env):
    module, client = docker_env
    provider = _docker_provider(module)
    principal = SandboxPrincipal(subject="a")
    policy = SandboxPolicy(network_egress="deny", cpu=1.5, memory_mb=512, fs_allow_write=["/workspace"])
    await provider.create(principal=principal, policy=policy)
    _, kwargs = client.containers.run_calls[0]
    assert kwargs["network_mode"] == "none"
    assert kwargs["nano_cpus"] == 1_500_000_000
    assert kwargs["mem_limit"] == "512m"
    assert kwargs["read_only"] is True
    assert kwargs["tmpfs"] == {"/workspace": ""}


@pytest.mark.asyncio
async def test_docker_allowlist_fails_closed_under_strict(docker_env):
    module, client = docker_env
    provider = _docker_provider(module)
    principal = SandboxPrincipal(subject="a")
    with pytest.raises(SandboxPolicyError):
        await provider.create(principal=principal, policy=SandboxPolicy(network_egress="allowlist", strict=True))
    assert client.containers.run_calls == []  # rejected before any daemon call

    relaxed = SandboxPolicy(network_egress="allowlist", strict=False)
    await provider.create(principal=principal, policy=relaxed)
    _, kwargs = client.containers.run_calls[0]
    assert "network_mode" not in kwargs  # proceeds with unrestricted egress


@pytest.mark.asyncio
async def test_docker_execute_call_shape_and_to_thread(docker_env):
    module, _client = docker_env
    provider = _docker_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    result = await sandbox.execute_code("print('hi')")
    container = sandbox._container
    assert container.exec_calls[0] == (["python", "-c", "print('hi')"], "/workspace")
    assert container.exec_threads[0] is not threading.current_thread()  # sync SDK runs in to_thread
    assert result.stdout == "fake stdout" and result.exit_code == 0

    await sandbox.execute_command("ls -la")
    assert container.exec_calls[1][0] == ["/bin/sh", "-c", "ls -la"]

    await sandbox.install_packages(["requests"])
    assert container.exec_calls[2][0] == ["pip", "install", "requests"]

    with pytest.raises(SandboxCapabilityError):
        await sandbox.execute_code("echo hi", "bash")  # undeclared language


@pytest.mark.asyncio
async def test_docker_timeout_raises_and_best_effort_kills(docker_env):
    module, _client = docker_env
    provider = _docker_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    container = sandbox._container
    container.exec_delay = 0.5
    with pytest.raises(SandboxTimeoutError):
        await sandbox.execute_code("while True: pass", timeout=0.05)
    container.exec_delay = 0.0
    await asyncio.sleep(0.6)  # let the abandoned exec thread finish recording
    assert any(call[0][0] == "pkill" for call in container.exec_calls)


@pytest.mark.asyncio
async def test_docker_file_roundtrip_via_archives(docker_env):
    module, _client = docker_env
    provider = _docker_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    await sandbox.upload_file("data/notes.txt", b"hello docker")
    assert await sandbox.download_file("data/notes.txt") == b"hello docker"


@pytest.mark.asyncio
async def test_docker_file_ops_reject_path_traversal(docker_env):
    module, _client = docker_env
    provider = _docker_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    # `..` traversal that escapes the workdir is rejected.
    for bad in ["../etc/passwd", "a/../../escape"]:
        with pytest.raises(SandboxPolicyError):
            await sandbox.upload_file(bad, b"nope")
        with pytest.raises(SandboxPolicyError):
            await sandbox.download_file(bad)
    # An absolute path is neutralized to a workdir-relative one (not an escape), like
    # local_subprocess: `/notes.txt` -> `<workdir>/notes.txt`.
    await sandbox.upload_file("/notes.txt", b"remapped")
    assert await sandbox.download_file("/notes.txt") == b"remapped"


@pytest.mark.asyncio
async def test_docker_attach_start_and_gone(docker_env):
    module, client = docker_env
    provider = _docker_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)

    container = client.containers.by_id[sandbox.id]
    container.status = "exited"
    reattached = await provider.attach(sandbox.id, principal=principal, policy=policy)
    assert reattached.id == sandbox.id
    assert container.started is True  # stopped containers are started on attach

    with pytest.raises(SandboxGoneError):
        await provider.attach("no-such-container", principal=principal, policy=policy)


@pytest.mark.asyncio
async def test_docker_attach_to_config_skips_create(docker_env):
    module, client = docker_env
    existing = FakeContainer("pre-existing")
    client.containers.by_id["pre-existing"] = existing
    provider = _docker_provider(module, _SandboxDockerConfig(attach_to="pre-existing"))
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    assert sandbox.id == "pre-existing"
    assert client.containers.run_calls == []  # mode 3: never provisions


@pytest.mark.asyncio
async def test_docker_close_keeps_container_destroy_removes(docker_env):
    module, client = docker_env
    provider = _docker_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    container = client.containers.by_id[sandbox.id]

    await sandbox.close()
    assert container.removed is False  # close leaves the container running (reattachable)

    await provider.destroy(sandbox.id)
    assert container.removed is True
    await provider.destroy("unknown-id")  # NotFound is a no-op


# --------------------------------------------------------------------------- #
# ec2_ssm — mocked boto3: attach-only semantics, call shapes, identity mapping
# --------------------------------------------------------------------------- #


class FakeClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeSSMClient:
    def __init__(self, instances):
        self.instances = set(instances)
        self.send_calls = []
        self.send_threads = []
        self.invocation_calls = []
        self.cancel_calls = []
        self.describe_calls = []
        self.pending_polls = 0  # invocations report InProgress this many times before terminal
        self.missing_polls = 0  # invocations raise InvocationDoesNotExist this many times first
        self.invocation = {
            "Status": "Success",
            "StandardOutputContent": "ssm stdout",
            "StandardErrorContent": "",
            "ResponseCode": 0,
        }

    def describe_instance_information(self, Filters):
        self.describe_calls.append(Filters)
        wanted = Filters[0]["Values"]
        found = [i for i in wanted if i in self.instances]
        return {"InstanceInformationList": [{"InstanceId": i} for i in found]}

    def send_command(self, **kwargs):
        self.send_threads.append(threading.current_thread())
        self.send_calls.append(kwargs)
        if kwargs["InstanceIds"][0] not in self.instances:
            raise FakeClientError("InvalidInstanceId")
        return {"Command": {"CommandId": f"cmd-{len(self.send_calls)}"}}

    def get_command_invocation(self, CommandId, InstanceId):
        self.invocation_calls.append((CommandId, InstanceId))
        if self.missing_polls > 0:  # SSM has not registered the invocation yet
            self.missing_polls -= 1
            raise FakeClientError("InvocationDoesNotExist")
        if self.pending_polls > 0:
            self.pending_polls -= 1
            return {"Status": "InProgress"}
        return dict(self.invocation)

    def cancel_command(self, CommandId):
        self.cancel_calls.append(CommandId)


class FakeSTSClient:
    def __init__(self):
        self.assume_calls = []

    def assume_role(self, **kwargs):
        self.assume_calls.append(kwargs)
        return {
            "Credentials": {
                "AccessKeyId": "AKIA-TEST",
                "SecretAccessKey": "secret",
                "SessionToken": "token",
            }
        }


@pytest.fixture
def ssm_env(monkeypatch):
    """Import the provider module against a fake boto3 and return (module, fake_boto3)."""
    ssm = FakeSSMClient(instances={"i-abc123"})
    sts = FakeSTSClient()

    class FakeBoto3:
        client_calls = []

        @staticmethod
        def client(service, **kwargs):
            FakeBoto3.client_calls.append((service, kwargs))
            return {"ssm": ssm, "sts": sts}[service]

    fake = types.SimpleNamespace(client=FakeBoto3.client, client_calls=FakeBoto3.client_calls, ssm=ssm, sts=sts)
    monkeypatch.setitem(sys.modules, "boto3", fake)
    module = importlib.import_module("agentkernel.sandbox.providers.ec2_ssm")
    monkeypatch.setattr(module, "boto3", fake)  # rebind in case it was imported earlier
    return module, fake


def _ssm_provider(module, config=None):
    from agentkernel.core.config import _SandboxEC2SSMConfig

    return module.EC2SSMSandboxProvider(config or _SandboxEC2SSMConfig(region="us-east-1", attach_to="i-abc123"))


@pytest.mark.asyncio
async def test_ssm_create_is_attach_only(ssm_env):
    from agentkernel.core.config import _SandboxEC2SSMConfig
    from agentkernel.sandbox.errors import SandboxConfigError

    module, fake = ssm_env
    provider = _ssm_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    assert sandbox.id == "i-abc123"  # bound to attach_to; never provisions
    assert fake.ssm.describe_calls[0][0] == {"Key": "InstanceIds", "Values": ["i-abc123"]}

    # Without attach_to, create fails loud instead of provisioning.
    bare = module.EC2SSMSandboxProvider(_SandboxEC2SSMConfig())
    with pytest.raises(SandboxConfigError):
        await bare.create(principal=principal, policy=policy)


@pytest.mark.asyncio
async def test_ssm_attach_gone_when_not_registered(ssm_env):
    module, _fake = ssm_env
    provider = _ssm_provider(module)
    principal, policy = _principal_policy()
    with pytest.raises(SandboxGoneError):
        await provider.attach("i-unknown", principal=principal, policy=policy)


@pytest.mark.asyncio
async def test_ssm_command_call_shape_and_to_thread(ssm_env):
    module, fake = ssm_env
    provider = _ssm_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    result = await sandbox.execute_command("uname -a")
    call = fake.ssm.send_calls[0]
    assert call["InstanceIds"] == ["i-abc123"]
    assert call["DocumentName"] == "AWS-RunShellScript"
    assert call["Parameters"] == {"commands": ["uname -a"]}
    assert fake.ssm.send_threads[0] is not threading.current_thread()  # sync SDK runs in to_thread
    assert result.stdout == "ssm stdout" and result.exit_code == 0
    assert fake.ssm.invocation_calls[0] == ("cmd-1", "i-abc123")


@pytest.mark.asyncio
async def test_ssm_polls_until_terminal_status(ssm_env):
    module, fake = ssm_env
    monkeypatch_interval = 0.01
    module_interval = module._POLL_INTERVAL
    try:
        module._POLL_INTERVAL = monkeypatch_interval
        provider = _ssm_provider(module)
        principal, policy = _principal_policy()
        sandbox = await provider.create(principal=principal, policy=policy)
        fake.ssm.pending_polls = 2
        result = await sandbox.execute_command("sleep-ish")
        assert result.exit_code == 0
        assert len(fake.ssm.invocation_calls) == 3  # two InProgress polls + the terminal one
    finally:
        module._POLL_INTERVAL = module_interval


@pytest.mark.asyncio
async def test_ssm_waits_out_unregistered_invocation(ssm_env):
    """SendCommand -> GetCommandInvocation is eventually consistent; the gap is not a failure."""
    module, fake = ssm_env
    module_interval = module._POLL_INTERVAL
    try:
        module._POLL_INTERVAL = 0.01
        provider = _ssm_provider(module)
        principal, policy = _principal_policy()
        sandbox = await provider.create(principal=principal, policy=policy)
        fake.ssm.missing_polls = 2
        result = await sandbox.execute_command("uname -a")
        assert result.exit_code == 0 and result.stdout == "ssm stdout"
        assert len(fake.ssm.invocation_calls) == 3  # two missing polls + the terminal one
        assert len(fake.ssm.send_calls) == 1  # waited rather than re-sending
    finally:
        module._POLL_INTERVAL = module_interval


@pytest.mark.asyncio
async def test_ssm_unregistered_invocation_still_times_out(ssm_env):
    """A never-registered invocation ends as SandboxTimeoutError, not an infinite wait."""
    module, fake = ssm_env
    provider = _ssm_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    fake.ssm.missing_polls = 10_000
    with pytest.raises(SandboxTimeoutError):
        await sandbox.execute_command("uname", timeout=0.05)


@pytest.mark.asyncio
async def test_ssm_execute_code_wraps_python_heredoc(ssm_env):
    module, fake = ssm_env
    provider = _ssm_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    await sandbox.execute_code("print(6 * 7)")
    command = fake.ssm.send_calls[0]["Parameters"]["commands"][0]
    delim = module._HEREDOC_DELIMITER
    assert command == f"python3 - <<'{delim}'\nprint(6 * 7)\n{delim}"

    with pytest.raises(SandboxCapabilityError):
        await sandbox.execute_code("echo hi", "bash")  # undeclared language


@pytest.mark.asyncio
async def test_ssm_execute_code_heredoc_avoids_delimiter_collision(ssm_env):
    """Code that contains the default delimiter as a line must not terminate the heredoc
    early — the provider picks a collision-free delimiter instead."""
    module, fake = ssm_env
    provider = _ssm_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)

    code = f"print('a')\n{module._HEREDOC_DELIMITER}\nprint('b')"  # delimiter appears mid-code
    await sandbox.execute_code(code)
    command = fake.ssm.send_calls[0]["Parameters"]["commands"][0]
    used = command.split("<<'", 1)[1].split("'", 1)[0]
    assert used != module._HEREDOC_DELIMITER  # bumped to avoid the embedded line
    assert command == f"python3 - <<'{used}'\n{code}\n{used}"
    assert used not in code.splitlines()  # the chosen delimiter is genuinely collision-free


def test_ssm_role_session_name_sanitizes_and_clamps():
    from agentkernel.sandbox.providers.ec2_ssm import _role_session_name

    # allowed characters pass through
    assert _role_session_name("alice") == "ak-sandbox-alice"
    # characters outside [\w+=,.@-] (e.g. ':' '/' in an ARN-like subject) are replaced
    name = _role_session_name("arn:aws:iam::1:user/alice")
    assert ":" not in name and "/" not in name
    assert __import__("re").fullmatch(r"[\w+=,.@-]{2,64}", name)
    # long subjects clamp to 64 chars
    assert len(_role_session_name("x" * 200)) == 64


@pytest.mark.asyncio
async def test_ssm_user_mode_assumes_role_and_runs_as(ssm_env, monkeypatch):
    module, fake = ssm_env
    provider = _ssm_provider(module)
    # The assumed-role client is built via botocore's auto-refreshing provider; patch that
    # seam to record (region, role_arn, subject) and hand back the fake SSM client.
    assume_calls = []

    def fake_assumed_role_client(region, role_arn, subject):
        assume_calls.append((region, role_arn, subject))
        return fake.ssm

    monkeypatch.setattr(module.EC2SSMSandboxProvider, "_assumed_role_client", staticmethod(fake_assumed_role_client))
    principal = SandboxPrincipal(
        mode="user",
        subject="alice",
        credentials={"role_arn": "arn:aws:iam::1:role/dev", "run_as": "alice"},
    )
    sandbox = await provider.attach("i-abc123", principal=principal, policy=SandboxPolicy())

    assert assume_calls == [("us-east-1", "arn:aws:iam::1:role/dev", "alice")]  # role assumed once

    await sandbox.execute_command("whoami")
    command = fake.ssm.send_calls[0]["Parameters"]["commands"][0]
    assert command.startswith("sudo -n -u alice sh -c ")  # RunAs realized as a sudo prefix
    assert "whoami" in command


@pytest.mark.asyncio
async def test_ssm_user_mode_caches_assumed_client_per_subject_role(ssm_env, monkeypatch):
    """A per_session user profile re-attaches on every execution; the assumed-role client is
    cached per (subject, role_arn), so the role is assumed once, not once per execution."""
    module, fake = ssm_env
    provider = _ssm_provider(module)
    assume_calls = []

    def fake_assumed_role_client(region, role_arn, subject):
        assume_calls.append((region, role_arn, subject))
        return fake.ssm

    monkeypatch.setattr(module.EC2SSMSandboxProvider, "_assumed_role_client", staticmethod(fake_assumed_role_client))
    principal = SandboxPrincipal(mode="user", subject="alice", credentials={"role_arn": "arn:aws:iam::1:role/dev"})

    # Two acquisitions (as the worker does across executions) -> one assume_role.
    await provider.attach("i-abc123", principal=principal, policy=SandboxPolicy())
    await provider.attach("i-abc123", principal=principal, policy=SandboxPolicy())
    assert len(assume_calls) == 1

    # A different subject is a distinct identity -> its own assumption.
    other = SandboxPrincipal(mode="user", subject="bob", credentials={"role_arn": "arn:aws:iam::1:role/dev"})
    await provider.attach("i-abc123", principal=other, policy=SandboxPolicy())
    assert len(assume_calls) == 2


@pytest.mark.asyncio
async def test_ssm_user_mode_without_role_arn_fails_closed(ssm_env):
    module, _fake = ssm_env
    provider = _ssm_provider(module)
    principal = SandboxPrincipal(mode="user", subject="alice")
    with pytest.raises(SandboxPolicyError):
        await provider.attach("i-abc123", principal=principal, policy=SandboxPolicy())


@pytest.mark.asyncio
async def test_ssm_timeout_raises_and_best_effort_cancels(ssm_env):
    module, fake = ssm_env
    provider = _ssm_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    fake.ssm.pending_polls = 10_000  # never reaches a terminal status
    with pytest.raises(SandboxTimeoutError):
        await sandbox.execute_command("spin", timeout=0.05)
    assert fake.ssm.cancel_calls == ["cmd-1"]


@pytest.mark.asyncio
async def test_ssm_invalid_instance_maps_to_gone(ssm_env):
    module, fake = ssm_env
    provider = _ssm_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    fake.ssm.instances.clear()  # instance vanished between attach and execute
    with pytest.raises(SandboxGoneError):
        await sandbox.execute_command("uname")


@pytest.mark.asyncio
async def test_ssm_close_and_destroy_are_no_ops(ssm_env):
    from agentkernel.sandbox.base import AttachedEnvironment

    module, fake = ssm_env
    provider = _ssm_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    # The handle is an AttachedEnvironment, not a plain Sandbox: it fronts an instance the
    # framework never owns, so releasing it must never affect the instance.
    assert isinstance(sandbox, AttachedEnvironment)
    await sandbox.close()
    await sandbox.close()  # idempotent
    await provider.destroy(sandbox.id)  # never owns the host
    await provider.destroy("i-unknown")  # unknown id is a no-op
    assert fake.ssm.send_calls == []  # none of the above touched the instance


# --------------------------------------------------------------------------- #
# e2b — mocked async SDK: call shapes, policy mapping, native idle timeout
# --------------------------------------------------------------------------- #


class FakeE2BNotFound(Exception):
    pass


class FakeCommandExit(Exception):
    def __init__(self, stdout, stderr, exit_code):
        super().__init__(f"exit {exit_code}")
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code


@pytest.fixture
def e2b_env(monkeypatch):
    """Import the provider module against a fake e2b SDK and return (module, fake_cls)."""

    class FakeExecution:
        def __init__(self, stdout=("e2b out",), stderr=(), error=None):
            self.logs = types.SimpleNamespace(stdout=list(stdout), stderr=list(stderr))
            self.error = error

    class FakeAsyncSandbox:
        instances: dict = {}
        create_calls: list = []
        connect_calls: list = []
        kill_calls: list = []
        next_execution: FakeExecution = FakeExecution()
        next_command_error: Exception | None = None

        def __init__(self, sandbox_id):
            self.sandbox_id = sandbox_id
            self.run_calls = []
            self.command_calls = []
            self.files_store = {}

            async def run(cmd, timeout=None):
                self.command_calls.append((cmd, timeout))
                if FakeAsyncSandbox.next_command_error is not None:
                    raise FakeAsyncSandbox.next_command_error
                return types.SimpleNamespace(stdout="cmd out", stderr="", exit_code=0)

            async def write(path, data):
                self.files_store[path] = data

            async def read(path, format="text"):
                if path not in self.files_store:
                    raise FileNotFoundError(path)
                return bytearray(self.files_store[path])

            self.commands = types.SimpleNamespace(run=run)
            self.files = types.SimpleNamespace(write=write, read=read)

        async def run_code(self, code, timeout=None):
            self.run_calls.append((code, timeout))
            return FakeAsyncSandbox.next_execution

        @classmethod
        async def create(cls, **kwargs):
            cls.create_calls.append(kwargs)
            sandbox = cls(f"e2b-{len(cls.create_calls)}")
            cls.instances[sandbox.sandbox_id] = sandbox
            return sandbox

        @classmethod
        async def connect(cls, sandbox_id, **kwargs):
            cls.connect_calls.append((sandbox_id, kwargs))
            if sandbox_id not in cls.instances:
                raise FakeE2BNotFound(sandbox_id)
            return cls.instances[sandbox_id]

        @classmethod
        async def kill(cls, sandbox_id, **kwargs):
            cls.kill_calls.append((sandbox_id, kwargs))
            if sandbox_id not in cls.instances:
                raise FakeE2BNotFound(sandbox_id)
            del cls.instances[sandbox_id]
            return True

    exceptions_mod = types.SimpleNamespace(NotFoundException=FakeE2BNotFound)
    handle_mod = types.SimpleNamespace(CommandExitException=FakeCommandExit)
    for name, mod in {
        "e2b": types.SimpleNamespace(exceptions=exceptions_mod),
        "e2b.exceptions": exceptions_mod,
        "e2b.sandbox": types.SimpleNamespace(),
        "e2b.sandbox.commands": types.SimpleNamespace(),
        "e2b.sandbox.commands.command_handle": handle_mod,
        "e2b_code_interpreter": types.SimpleNamespace(AsyncSandbox=FakeAsyncSandbox),
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)
    module = importlib.import_module("agentkernel.sandbox.providers.e2b")
    monkeypatch.setattr(module, "AsyncSandbox", FakeAsyncSandbox)
    monkeypatch.setattr(module, "NotFoundException", FakeE2BNotFound)
    monkeypatch.setattr(module, "CommandExitException", FakeCommandExit)
    monkeypatch.setenv("E2B_API_KEY", "e2b-test-key")
    return module, FakeAsyncSandbox


def _e2b_provider(module, config=None, idle_timeout=None):
    from agentkernel.core.config import _SandboxE2BConfig

    return module.E2BSandboxProvider(config or _SandboxE2BConfig(), idle_timeout=idle_timeout)


@pytest.mark.asyncio
async def test_e2b_create_call_shape_and_idle_timeout_passthrough(e2b_env):
    from agentkernel.core.config import _SandboxE2BConfig

    module, fake_cls = e2b_env
    provider = _e2b_provider(module, _SandboxE2BConfig(template="my-template"), idle_timeout=7200)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    kwargs = fake_cls.create_calls[0]
    assert kwargs["template"] == "my-template"
    assert kwargs["api_key"] == "e2b-test-key"
    assert kwargs["timeout"] == 7200  # native auto-stop: profile idle_timeout passed at create
    assert "allow_internet_access" not in kwargs and "network" not in kwargs
    assert sandbox.id == "e2b-1"


@pytest.mark.asyncio
async def test_e2b_network_policy_mapping(e2b_env):
    module, fake_cls = e2b_env
    provider = _e2b_provider(module)
    principal = SandboxPrincipal(subject="a")

    await provider.create(principal=principal, policy=SandboxPolicy(network_egress="deny"))
    assert fake_cls.create_calls[0]["allow_internet_access"] is False

    await provider.create(
        principal=principal,
        policy=SandboxPolicy(network_egress="allowlist", network_allow=["pypi.org", "10.0.0.0/8"]),
    )
    assert fake_cls.create_calls[1]["network"] == {"allow_out": ["pypi.org", "10.0.0.0/8"]}


@pytest.mark.asyncio
async def test_e2b_missing_api_key_fails_loud(e2b_env, monkeypatch):
    from agentkernel.sandbox.errors import SandboxConfigError

    module, _fake_cls = e2b_env
    monkeypatch.delenv("E2B_API_KEY")
    provider = _e2b_provider(module)
    principal, policy = _principal_policy()
    with pytest.raises(SandboxConfigError):
        await provider.create(principal=principal, policy=policy)


@pytest.mark.asyncio
async def test_e2b_run_code_maps_execution_to_result(e2b_env):
    module, fake_cls = e2b_env
    provider = _e2b_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)

    result = await sandbox.execute_code("print('hi')", timeout=30)
    assert sandbox._sandbox.run_calls[0] == ("print('hi')", 30)
    assert result.stdout == "e2b out" and result.exit_code == 0

    fake_cls.next_execution = type(fake_cls.next_execution)(
        stdout=(), stderr=("boom",), error=types.SimpleNamespace(name="ValueError", value="bad", traceback="")
    )
    failed = await sandbox.execute_code("raise ValueError('bad')")
    assert failed.exit_code == 1  # execution error is data, not an exception
    assert "ValueError: bad" in failed.stderr

    with pytest.raises(SandboxCapabilityError):
        await sandbox.execute_code("echo hi", "bash")  # undeclared language


@pytest.mark.asyncio
async def test_e2b_command_nonzero_exit_is_result_not_exception(e2b_env):
    module, fake_cls = e2b_env
    provider = _e2b_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)

    ok = await sandbox.execute_command("echo hi")
    assert ok.stdout == "cmd out" and ok.exit_code == 0

    fake_cls.next_command_error = FakeCommandExit(stdout="", stderr="not found", exit_code=127)
    failed = await sandbox.execute_command("missing-binary")
    assert failed.exit_code == 127 and failed.stderr == "not found"
    fake_cls.next_command_error = None

    await sandbox.install_packages(["requests", "httpx"])
    assert sandbox._sandbox.command_calls[-1][0] == "pip install requests httpx"


@pytest.mark.asyncio
async def test_e2b_file_roundtrip(e2b_env):
    module, _fake_cls = e2b_env
    provider = _e2b_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    await sandbox.upload_file("notes.txt", b"hello e2b")
    data = await sandbox.download_file("notes.txt")
    assert data == b"hello e2b" and isinstance(data, bytes)


@pytest.mark.asyncio
async def test_e2b_attach_connect_and_gone(e2b_env):
    module, fake_cls = e2b_env
    provider = _e2b_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)

    reattached = await provider.attach(sandbox.id, principal=principal, policy=policy)
    assert reattached.id == sandbox.id
    assert fake_cls.connect_calls[0][0] == sandbox.id
    assert fake_cls.connect_calls[0][1]["api_key"] == "e2b-test-key"

    with pytest.raises(SandboxGoneError):
        await provider.attach("e2b-ghost", principal=principal, policy=policy)


@pytest.mark.asyncio
async def test_e2b_close_keeps_sandbox_destroy_kills(e2b_env):
    module, fake_cls = e2b_env
    provider = _e2b_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)

    await sandbox.close()
    assert sandbox.id in fake_cls.instances  # close leaves the sandbox running (reattachable)

    await provider.destroy(sandbox.id)
    assert sandbox.id not in fake_cls.instances
    assert fake_cls.kill_calls[0][0] == sandbox.id
    await provider.destroy(sandbox.id)  # already gone is a no-op


# --------------------------------------------------------------------------- #
# daytona — mocked sync SDK: call shapes, policy mapping, to_thread, auto-stop
# --------------------------------------------------------------------------- #


class FakeDaytonaError(Exception):
    pass


@pytest.fixture
def daytona_env(monkeypatch):
    """Import the provider module against a fake daytona SDK and return (module, client)."""

    class FakeSnapshotParams:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeImageParams:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeResources:
        def __init__(self, cpu=None, memory=None):
            self.cpu = cpu
            self.memory = memory

    class FakeDaytonaConfig:
        def __init__(self, api_key=None, target=None):
            self.api_key = api_key
            self.target = target

    class FakeDaytonaSandbox:
        def __init__(self, sandbox_id):
            self.id = sandbox_id
            self.code_calls = []
            self.exec_calls = []
            self.exec_threads = []
            self.files_store = {}
            self.next_exit_code = 0
            self.next_result = "daytona out"

            outer = self

            # timeout is keyword-only here on purpose: the provider passes it by keyword, so a
            # regression back to positional args (the fragility the PR review flagged) would
            # raise TypeError instead of silently binding to the wrong parameter.
            def code_run(code, params=None, *, timeout=None):
                outer.code_calls.append((code, params, timeout))
                outer.exec_threads.append(threading.current_thread())
                return types.SimpleNamespace(exit_code=outer.next_exit_code, result=outer.next_result)

            def exec_(command, *, cwd=None, env=None, timeout=None):
                outer.exec_calls.append((command, cwd, env, timeout))
                outer.exec_threads.append(threading.current_thread())
                return types.SimpleNamespace(exit_code=outer.next_exit_code, result=outer.next_result)

            def upload_file(src, dst, timeout=1800):
                outer.files_store[dst] = src

            def download_file(path):
                if path not in outer.files_store:
                    return None
                return outer.files_store[path]

            self.process = types.SimpleNamespace(code_run=code_run, exec=exec_)
            self.fs = types.SimpleNamespace(upload_file=upload_file, download_file=download_file)

    class FakeDaytonaClient:
        def __init__(self, config=None):
            FakeDaytonaClient.last_config = config
            FakeDaytonaClient.instances = {}
            FakeDaytonaClient.create_calls = []
            FakeDaytonaClient.delete_calls = []

        def create(self, params=None, **kwargs):
            FakeDaytonaClient.create_calls.append(params)
            sandbox = FakeDaytonaSandbox(f"dt-{len(FakeDaytonaClient.create_calls)}")
            FakeDaytonaClient.instances[sandbox.id] = sandbox
            return sandbox

        def get(self, sandbox_id):
            if sandbox_id not in FakeDaytonaClient.instances:
                raise FakeDaytonaError(sandbox_id)
            return FakeDaytonaClient.instances[sandbox_id]

        def delete(self, sandbox):
            FakeDaytonaClient.delete_calls.append(sandbox.id)
            FakeDaytonaClient.instances.pop(sandbox.id, None)

    errors_mod = types.SimpleNamespace(DaytonaError=FakeDaytonaError)
    sdk_mod = types.SimpleNamespace(
        Daytona=FakeDaytonaClient,
        DaytonaConfig=FakeDaytonaConfig,
        CreateSandboxFromSnapshotParams=FakeSnapshotParams,
        CreateSandboxFromImageParams=FakeImageParams,
        Resources=FakeResources,
        common=types.SimpleNamespace(errors=errors_mod),
    )
    for name, mod in {
        "daytona": sdk_mod,
        "daytona.common": sdk_mod.common,
        "daytona.common.errors": errors_mod,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)
    module = importlib.import_module("agentkernel.sandbox.providers.daytona")
    for attr, value in {
        "Daytona": FakeDaytonaClient,
        "DaytonaConfig": FakeDaytonaConfig,
        "CreateSandboxFromSnapshotParams": FakeSnapshotParams,
        "CreateSandboxFromImageParams": FakeImageParams,
        "Resources": FakeResources,
        "DaytonaError": FakeDaytonaError,
    }.items():
        monkeypatch.setattr(module, attr, value)
    monkeypatch.setenv("DAYTONA_API_KEY", "daytona-test-key")
    return module, FakeDaytonaClient


def _daytona_provider(module, config=None, idle_timeout=None):
    from agentkernel.core.config import _SandboxDaytonaConfig

    return module.DaytonaSandboxProvider(config or _SandboxDaytonaConfig(target="us"), idle_timeout=idle_timeout)


@pytest.mark.asyncio
async def test_daytona_create_call_shape_and_auto_stop(daytona_env):
    module, client_cls = daytona_env
    provider = _daytona_provider(module, idle_timeout=3600)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)

    assert client_cls.last_config.api_key == "daytona-test-key"
    assert client_cls.last_config.target == "us"
    params = client_cls.create_calls[0]
    assert type(params).__name__ == "FakeSnapshotParams"  # snapshot-based by default
    assert params.kwargs["language"] == "python"
    assert params.kwargs["auto_stop_interval"] == 60  # 3600 s -> 60 min (native auto-stop)
    assert sandbox.id == "dt-1"


@pytest.mark.asyncio
async def test_daytona_auto_stop_rounds_up(daytona_env):
    module, client_cls = daytona_env
    provider = _daytona_provider(module, idle_timeout=90)
    principal, policy = _principal_policy()
    await provider.create(principal=principal, policy=policy)
    assert client_cls.create_calls[0].kwargs["auto_stop_interval"] == 2  # 90 s -> ceil to 2 min


@pytest.mark.asyncio
async def test_daytona_network_policy_mapping(daytona_env):
    module, client_cls = daytona_env
    provider = _daytona_provider(module)
    principal = SandboxPrincipal(subject="a")

    await provider.create(principal=principal, policy=SandboxPolicy(network_egress="deny"))
    assert client_cls.create_calls[0].kwargs["network_block_all"] is True

    await provider.create(
        principal=principal,
        policy=SandboxPolicy(network_egress="allowlist", network_allow=["10.0.0.0/8", "192.168.0.0/16"]),
    )
    assert client_cls.create_calls[1].kwargs["network_allow_list"] == "10.0.0.0/8,192.168.0.0/16"


@pytest.mark.asyncio
async def test_daytona_resource_policy_uses_image_params(daytona_env):
    module, client_cls = daytona_env
    provider = _daytona_provider(module)
    principal = SandboxPrincipal(subject="a")
    await provider.create(principal=principal, policy=SandboxPolicy(cpu=1.5, memory_mb=512))
    params = client_cls.create_calls[0]
    assert type(params).__name__ == "FakeImageParams"  # resources need an image-based sandbox
    assert params.kwargs["image"] == module._DEFAULT_IMAGE
    resources = params.kwargs["resources"]
    assert resources.cpu == 2  # 1.5 cores rounded up
    assert resources.memory == 1  # 512 MB -> 1 GiB minimum


@pytest.mark.asyncio
async def test_daytona_config_image_takes_image_path(daytona_env):
    from agentkernel.core.config import _SandboxDaytonaConfig

    module, client_cls = daytona_env
    provider = _daytona_provider(module, _SandboxDaytonaConfig(image="ghcr.io/acme/py:1"))
    principal, policy = _principal_policy()
    await provider.create(principal=principal, policy=policy)  # no resource policy
    params = client_cls.create_calls[0]
    assert type(params).__name__ == "FakeImageParams"  # explicit image forces the image path
    assert params.kwargs["image"] == "ghcr.io/acme/py:1"
    assert "resources" not in params.kwargs  # none requested


@pytest.mark.asyncio
async def test_daytona_config_image_used_when_resources_present(daytona_env):
    from agentkernel.core.config import _SandboxDaytonaConfig

    module, client_cls = daytona_env
    provider = _daytona_provider(module, _SandboxDaytonaConfig(image="ghcr.io/acme/py:1"))
    principal = SandboxPrincipal(subject="a")
    await provider.create(principal=principal, policy=SandboxPolicy(cpu=1))
    params = client_cls.create_calls[0]
    assert params.kwargs["image"] == "ghcr.io/acme/py:1"  # config image, not the default
    assert params.kwargs["resources"].cpu == 1


@pytest.mark.asyncio
async def test_daytona_config_snapshot_takes_snapshot_path(daytona_env):
    from agentkernel.core.config import _SandboxDaytonaConfig

    module, client_cls = daytona_env
    provider = _daytona_provider(module, _SandboxDaytonaConfig(snapshot="warm-1"))
    principal, policy = _principal_policy()
    await provider.create(principal=principal, policy=policy)
    params = client_cls.create_calls[0]
    assert type(params).__name__ == "FakeSnapshotParams"
    assert params.kwargs["snapshot"] == "warm-1"


@pytest.mark.asyncio
async def test_daytona_config_env_vars_passed_through(daytona_env):
    from agentkernel.core.config import _SandboxDaytonaConfig

    module, client_cls = daytona_env
    provider = _daytona_provider(module, _SandboxDaytonaConfig(env_vars={"FOO": "bar"}))
    principal, policy = _principal_policy()
    await provider.create(principal=principal, policy=policy)
    assert client_cls.create_calls[0].kwargs["env_vars"] == {"FOO": "bar"}


@pytest.mark.asyncio
async def test_daytona_resources_against_snapshot_is_rejected(daytona_env):
    from agentkernel.core.config import _SandboxDaytonaConfig
    from agentkernel.sandbox.errors import SandboxConfigError

    module, _client_cls = daytona_env
    provider = _daytona_provider(module, _SandboxDaytonaConfig(snapshot="warm-1"))
    principal = SandboxPrincipal(subject="a")
    with pytest.raises(SandboxConfigError):  # resources need an image, not a snapshot
        await provider.create(principal=principal, policy=SandboxPolicy(memory_mb=512))


def test_daytona_config_image_snapshot_mutually_exclusive():
    from pydantic import ValidationError

    from agentkernel.core.config import _SandboxDaytonaConfig

    with pytest.raises(ValidationError):
        _SandboxDaytonaConfig(image="python:3.12-slim", snapshot="warm-1")


@pytest.mark.asyncio
async def test_daytona_missing_api_key_fails_loud(daytona_env, monkeypatch):
    from agentkernel.sandbox.errors import SandboxConfigError

    module, _client_cls = daytona_env
    monkeypatch.delenv("DAYTONA_API_KEY")
    provider = _daytona_provider(module)
    principal, policy = _principal_policy()
    with pytest.raises(SandboxConfigError):
        await provider.create(principal=principal, policy=policy)


@pytest.mark.asyncio
async def test_daytona_execute_call_shape_and_to_thread(daytona_env):
    module, _client_cls = daytona_env
    provider = _daytona_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)

    result = await sandbox.execute_code("print('hi')", timeout=30)
    inner = sandbox._sandbox
    assert inner.code_calls[0] == ("print('hi')", None, 30)
    assert inner.exec_threads[0] is not threading.current_thread()  # sync SDK runs in to_thread
    assert result.stdout == "daytona out" and result.exit_code == 0

    await sandbox.execute_command("ls -la")
    assert inner.exec_calls[0][0] == "ls -la"

    await sandbox.install_packages(["requests"])
    assert inner.exec_calls[1][0] == "pip install requests"

    inner.next_exit_code = 3
    inner.next_result = "boom"
    failed = await sandbox.execute_command("exit 3")
    assert failed.exit_code == 3 and failed.stderr == "boom"  # non-zero exit is data

    with pytest.raises(SandboxCapabilityError):
        await sandbox.execute_code("echo hi", "bash")  # undeclared language


@pytest.mark.asyncio
async def test_daytona_file_roundtrip_and_missing_file(daytona_env):
    module, _client_cls = daytona_env
    provider = _daytona_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    await sandbox.upload_file("notes.txt", b"hello daytona")
    assert await sandbox.download_file("notes.txt") == b"hello daytona"
    with pytest.raises(FileNotFoundError):
        await sandbox.download_file("missing.txt")


@pytest.mark.asyncio
async def test_daytona_attach_get_and_gone(daytona_env):
    module, client_cls = daytona_env
    provider = _daytona_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)

    reattached = await provider.attach(sandbox.id, principal=principal, policy=policy)
    assert reattached.id == sandbox.id

    with pytest.raises(SandboxGoneError):
        await provider.attach("dt-ghost", principal=principal, policy=policy)


@pytest.mark.asyncio
async def test_daytona_close_keeps_sandbox_destroy_deletes(daytona_env):
    module, client_cls = daytona_env
    provider = _daytona_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)

    await sandbox.close()
    assert sandbox.id in client_cls.instances  # close leaves the sandbox running (reattachable)

    await provider.destroy(sandbox.id)
    assert client_cls.delete_calls == [sandbox.id]
    await provider.destroy(sandbox.id)  # already gone is a no-op
    assert client_cls.delete_calls == [sandbox.id]


# --------------------------------------------------------------------------- #
# Factory passthrough — profile idle_timeout reaches the native-auto-stop providers
# --------------------------------------------------------------------------- #


def test_factory_passes_profile_idle_timeout_to_e2b(e2b_env):
    from agentkernel.core.config import _SandboxE2BConfig, _SandboxProfileConfig

    profile = _SandboxProfileConfig(type="e2b", e2b=_SandboxE2BConfig(), idle_timeout=7200)
    provider = SandboxProviderFactory._build("p", profile)
    assert provider._idle_timeout == 7200


def test_factory_passes_profile_idle_timeout_to_daytona(daytona_env):
    from agentkernel.core.config import _SandboxDaytonaConfig, _SandboxProfileConfig

    profile = _SandboxProfileConfig(type="daytona", daytona=_SandboxDaytonaConfig(), idle_timeout=90)
    provider = SandboxProviderFactory._build("p", profile)
    assert provider._idle_timeout == 90


# --------------------------------------------------------------------------- #
# kubernetes — mocked Kubernetes client (no cluster)
# --------------------------------------------------------------------------- #


class FakeApiException(Exception):
    def __init__(self, status):
        super().__init__(f"api error {status}")
        self.status = status


class _FakeK8sPod:
    def __init__(self, name, namespace, body, phase="Running"):
        self.name, self.namespace, self.body = name, namespace, body
        self.phase = phase
        self.deletion_timestamp = None
        self.conditions = []
        self.files: dict[str, bytes] = {}


class FakeK8sCluster:
    """In-memory pod/NetworkPolicy state plus a functional exec handler implementing the
    provider's base64-framed tar protocol, so the contract's files round trip is real."""

    def __init__(self):
        self.pods: dict[tuple[str, str], _FakeK8sPod] = {}
        self.netpols: dict[tuple[str, str], dict] = {}
        self.pod_creates: list[dict] = []
        self.pod_deletes: list[tuple[str, str]] = []
        self.netpol_deletes: list[tuple[str, str]] = []
        self.exec_calls: list[tuple[str, list, int]] = []  # (pod, command, thread ident)
        self.headers_log: list[tuple[str, dict]] = []  # (operation, request headers) for impersonation asserts
        self.api_clients: list = []  # every FakeApiClient the provider constructed
        self.default_phase = "Running"
        self.kubeconfig_loads: list = []
        self.incluster_loads: list = []
        self.exec_handler = self._default_exec

    def open_exec(self, name, namespace, kwargs, headers=None):
        pod = self.pods.get((namespace, name))
        if pod is None:
            raise FakeApiException(404)
        self.exec_calls.append((name, kwargs["command"], threading.get_ident()))
        self.headers_log.append(("exec", dict(headers or {})))
        return _FakeExecClient(pod, kwargs["command"], kwargs.get("stdin", False), self)

    @staticmethod
    def _default_exec(pod, command, stdin_data):
        if command[0] == "python" and command[1] == "-c":
            code = command[2]
            return ("", "simulated failure", 1) if FAIL_MARKER in code else (code, "", 0)
        if command[0] == "pip":
            return "installed", "", 0
        if command[0] in ("sh", "/bin/sh") and command[1] == "-c":
            shell_cmd = command[2]
            if "base64 -d | tar" in shell_cmd:  # the upload pipeline
                with tarfile.open(fileobj=io.BytesIO(base64.b64decode(stdin_data))) as tar:
                    for member in tar.getmembers():
                        if member.isfile():
                            pod.files[member.name] = tar.extractfile(member).read()
                return "", "", 0
            if shell_cmd.startswith("tar -cf"):  # the download pipeline
                rel = shlex.split(shell_cmd.split("|")[0])[-1]
                if rel not in pod.files:
                    return "", f"tar: {rel}: not found", 2
                buf = io.BytesIO()
                with tarfile.open(fileobj=buf, mode="w") as tar:
                    info = tarfile.TarInfo(name=rel)
                    info.size = len(pod.files[rel])
                    tar.addfile(info, io.BytesIO(pod.files[rel]))
                return base64.b64encode(buf.getvalue()).decode(), "", 0
            if shell_cmd.startswith("pkill"):
                return "", "", 0
            return ("", "simulated failure", 1) if FAIL_MARKER in shell_cmd else (shell_cmd, "", 0)
        return "", f"unknown command {command}", 127


class _FakeExecClient:
    """The WSClient surface the provider's exec loop drives."""

    def __init__(self, pod, command, needs_stdin, cluster):
        self._pod, self._command, self._cluster = pod, command, cluster
        self._needs_stdin = needs_stdin
        self._stdin: list[str] = []
        self._stdout = ""
        self._stderr = ""
        self.returncode = None
        self._open = True
        self._ran = False

    def write_stdin(self, data):
        self._stdin.append(data)

    def is_open(self):
        return self._open

    def update(self, timeout=None):
        if not self._ran and (not self._needs_stdin or self._stdin):
            stdin_data = "".join(self._stdin) if self._needs_stdin else None
            self._stdout, self._stderr, self.returncode = self._cluster.exec_handler(self._pod, self._command, stdin_data)
            self._ran = True
            self._open = False

    def peek_stdout(self):
        return bool(self._stdout)

    def read_stdout(self):
        out, self._stdout = self._stdout, ""
        return out

    def peek_stderr(self):
        return bool(self._stderr)

    def read_stderr(self):
        err, self._stderr = self._stderr, ""
        return err

    def close(self):
        self._open = False


class FakeApiClient:
    """Records the default headers set on it (the impersonation surface)."""

    def __init__(self, configuration=None):
        self.configuration = configuration
        self.headers: dict = {}

    def set_default_header(self, name, value):
        self.headers[name] = value


class FakeCoreV1:
    def __init__(self, cluster, api_client=None):
        self._cluster = cluster
        self._headers = dict(api_client.headers) if api_client is not None else {}

    def connect_get_namespaced_pod_exec(self):
        raise NotImplementedError("handed to stream(); the fake stream keys off the pod name and this method's __self__")

    def create_namespaced_pod(self, namespace, body):
        name = body["metadata"]["name"]
        self._cluster.pods[(namespace, name)] = _FakeK8sPod(name, namespace, body, phase=self._cluster.default_phase)
        self._cluster.pod_creates.append(body)
        self._cluster.headers_log.append(("create_pod", dict(self._headers)))

    def read_namespaced_pod(self, name, namespace):
        self._cluster.headers_log.append(("read_pod", dict(self._headers)))
        pod = self._cluster.pods.get((namespace, name))
        if pod is None:
            raise FakeApiException(404)
        return types.SimpleNamespace(
            metadata=types.SimpleNamespace(name=name, deletion_timestamp=pod.deletion_timestamp),
            status=types.SimpleNamespace(phase=pod.phase, conditions=pod.conditions),
        )

    def delete_namespaced_pod(self, name, namespace, **kwargs):
        self._cluster.headers_log.append(("delete_pod", dict(self._headers)))
        if (namespace, name) not in self._cluster.pods:
            raise FakeApiException(404)
        del self._cluster.pods[(namespace, name)]
        self._cluster.pod_deletes.append((namespace, name))


class FakeNetworkingV1:
    def __init__(self, cluster, api_client=None):
        self._cluster = cluster
        self._headers = dict(api_client.headers) if api_client is not None else {}

    def create_namespaced_network_policy(self, namespace, body):
        self._cluster.netpols[(namespace, body["metadata"]["name"])] = body
        self._cluster.headers_log.append(("create_netpol", dict(self._headers)))

    def delete_namespaced_network_policy(self, name, namespace, **kwargs):
        self._cluster.headers_log.append(("delete_netpol", dict(self._headers)))
        if (namespace, name) not in self._cluster.netpols:
            raise FakeApiException(404)
        del self._cluster.netpols[(namespace, name)]
        self._cluster.netpol_deletes.append((namespace, name))


@pytest.fixture
def k8s_env(monkeypatch):
    """Import the provider module against a fake kubernetes SDK and return (module, cluster)."""
    cluster = FakeK8sCluster()

    def _api_client(configuration=None):
        client = FakeApiClient(configuration)
        cluster.api_clients.append(client)
        return client

    client_ns = types.SimpleNamespace(
        CoreV1Api=lambda api_client=None: FakeCoreV1(cluster, api_client),
        NetworkingV1Api=lambda api_client=None: FakeNetworkingV1(cluster, api_client),
        ApiClient=_api_client,
        Configuration=types.SimpleNamespace(get_default_copy=lambda: object()),
        rest=types.SimpleNamespace(ApiException=FakeApiException),
    )
    config_ns = types.SimpleNamespace(
        load_kube_config=lambda config_file=None: cluster.kubeconfig_loads.append(config_file),
        load_incluster_config=lambda: cluster.incluster_loads.append(True),
    )
    # The fake stream resolves the calling client through the bound api method, so exec calls
    # carry that client's impersonation headers into the log.
    stream_ns = types.SimpleNamespace(
        stream=lambda api_method, name, namespace, **kwargs: cluster.open_exec(name, namespace, kwargs, api_method.__self__._headers)
    )
    fake_sdk = types.SimpleNamespace(client=client_ns, config=config_ns, stream=stream_ns)
    for module_name, module in [
        ("kubernetes", fake_sdk),
        ("kubernetes.client", client_ns),
        ("kubernetes.client.rest", client_ns.rest),
        ("kubernetes.config", config_ns),
        ("kubernetes.stream", stream_ns),
    ]:
        monkeypatch.setitem(sys.modules, module_name, module)
    module = importlib.import_module("agentkernel.sandbox.providers.kubernetes")
    monkeypatch.setattr(module, "kubernetes", fake_sdk)  # rebind in case it was imported earlier
    return module, cluster


def _k8s_provider(module, config=None, idle_timeout=1800):
    return module.KubernetesSandboxProvider(config or _SandboxKubernetesConfig(), idle_timeout=idle_timeout)


class TestKubernetesContract(SandboxProviderContract):
    """The public provider contract, run against the fake SDK (real tar/base64 file path)."""

    @pytest.fixture
    def provider(self, k8s_env):
        module, _cluster = k8s_env
        return _k8s_provider(module)


@pytest.mark.asyncio
async def test_k8s_pod_manifest_shape(k8s_env):
    module, cluster = k8s_env
    config = _SandboxKubernetesConfig(
        namespace="sb",
        image="hardened:1",
        service_account="sandbox-pod",
        image_pull_secrets=["regcred"],
        labels={"team": "ai"},
        node_selector={"pool": "sandbox"},
        env={"PYTHONUNBUFFERED": "1"},
        security_context={"fsGroup": 2000},
        container_security_context={"runAsNonRoot": True, "capabilities": {"drop": ["NET_RAW"]}},
    )
    provider = _k8s_provider(module, config, idle_timeout=900)
    principal, _ = _principal_policy()
    policy = SandboxPolicy(cpu=1.5, memory_mb=512, fs_allow_write=["/workspace"])
    sandbox = await provider.create(principal=principal, policy=policy)
    body = cluster.pod_creates[0]
    name = body["metadata"]["name"]
    assert name.startswith("ak-sandbox-") and sandbox.id == f"sb/{name}"
    labels = body["metadata"]["labels"]
    assert labels["app.kubernetes.io/managed-by"] == "agent-kernel" and labels["agentkernel.io/sandbox"] == "true"
    assert labels["team"] == "ai" and labels["agentkernel.io/sandbox-name"] == name
    spec = body["spec"]
    assert spec["restartPolicy"] == "Never" and spec["activeDeadlineSeconds"] == 1800  # 2 x idle_timeout
    assert spec["terminationGracePeriodSeconds"] == 5
    assert spec["serviceAccountName"] == "sandbox-pod"
    assert spec["imagePullSecrets"] == [{"name": "regcred"}] and spec["nodeSelector"] == {"pool": "sandbox"}
    assert spec["securityContext"] == {"fsGroup": 2000}
    assert spec["volumes"] == [{"name": "workspace", "emptyDir": {}}]
    container = spec["containers"][0]
    # sleep must be PID 1 directly: under `sh -c` the timeout path's `pkill sh` could kill PID 1.
    assert container["image"] == "hardened:1" and container["command"] == ["sleep", "infinity"]
    assert container["workingDir"] == "/workspace"
    assert container["env"] == [{"name": "PYTHONUNBUFFERED", "value": "1"}]
    assert container["resources"] == {"requests": {"cpu": "1.5", "memory": "512Mi"}, "limits": {"cpu": "1.5", "memory": "512Mi"}}
    assert container["volumeMounts"] == [{"name": "workspace", "mountPath": "/workspace"}]
    sc = container["securityContext"]
    assert sc["allowPrivilegeEscalation"] is False and sc["seccompProfile"] == {"type": "RuntimeDefault"}
    assert sc["capabilities"] == {"drop": ["NET_RAW"]}  # the config overlay wins per key
    assert sc["runAsNonRoot"] is True
    assert sc["readOnlyRootFilesystem"] is True  # policy enforcement wins over the overlay


@pytest.mark.asyncio
async def test_k8s_exec_argv_shapes_and_to_thread(k8s_env):
    module, cluster = k8s_env
    provider = _k8s_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    await sandbox.execute_code("print(1)")
    await sandbox.execute_command("echo hi")
    await sandbox.install_packages(["requests"])
    commands = [call[1] for call in cluster.exec_calls]
    assert commands[0] == ["python", "-c", "print(1)"]
    assert commands[1] == ["/bin/sh", "-c", "echo hi"]
    assert commands[2] == ["pip", "install", "requests"]
    assert all(ident != threading.get_ident() for _, _, ident in cluster.exec_calls)  # every SDK call off the event loop


@pytest.mark.asyncio
async def test_k8s_upload_download_binary_round_trip(k8s_env):
    module, _cluster = k8s_env
    provider = _k8s_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    payload = bytes([0, 255, 128, 10, 13, 200])
    await sandbox.upload_file("data/blob.bin", payload)
    assert await sandbox.download_file("data/blob.bin") == payload
    with pytest.raises(SandboxPolicyError):
        await sandbox.upload_file("../escape.txt", b"x")


@pytest.mark.asyncio
async def test_k8s_exec_timeout_kills_and_raises(k8s_env):
    module, cluster = k8s_env
    provider = _k8s_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    default_handler = cluster.exec_handler

    def slow_handler(pod, command, stdin_data):
        if command[0] == "python":
            time.sleep(5)
        return default_handler(pod, command, stdin_data)

    cluster.exec_handler = slow_handler
    with pytest.raises(SandboxTimeoutError):
        await sandbox.execute_code("while True: pass", timeout=0.05)
    assert cluster.exec_calls[-1][1] == ["sh", "-c", "pkill -9 python"]  # the best-effort kill


@pytest.mark.asyncio
async def test_k8s_attach_parsing_and_gone_signals(k8s_env):
    module, cluster = k8s_env
    provider = _k8s_provider(module)
    principal, policy = _principal_policy()
    cluster.pods[("other", "pod-x")] = _FakeK8sPod("pod-x", "other", {})
    cluster.pods[("default", "bare-pod")] = _FakeK8sPod("bare-pod", "default", {})
    assert (await provider.attach("other/pod-x", principal=principal, policy=policy)).id == "other/pod-x"
    assert (await provider.attach("bare-pod", principal=principal, policy=policy)).id == "default/bare-pod"  # bare name -> config namespace
    with pytest.raises(SandboxGoneError):
        await provider.attach("default/never-existed", principal=principal, policy=policy)
    cluster.pods[("default", "done-pod")] = _FakeK8sPod("done-pod", "default", {}, phase="Succeeded")
    with pytest.raises(SandboxGoneError):
        await provider.attach("done-pod", principal=principal, policy=policy)
    terminating = _FakeK8sPod("dying-pod", "default", {})
    terminating.deletion_timestamp = "2026-09-01T00:00:00Z"
    cluster.pods[("default", "dying-pod")] = terminating
    with pytest.raises(SandboxGoneError):
        await provider.attach("dying-pod", principal=principal, policy=policy)


@pytest.mark.asyncio
async def test_k8s_create_failure_leaves_no_orphan(k8s_env):
    module, cluster = k8s_env
    principal, policy = _principal_policy()
    cluster.default_phase = "Pending"
    provider = _k8s_provider(module, _SandboxKubernetesConfig(create_timeout=0.05))
    with pytest.raises(SandboxProvisionError, match="did not reach Running"):
        await provider.create(principal=principal, policy=policy)
    assert cluster.pods == {} and cluster.pod_deletes  # the failed create cleaned up after itself
    cluster.default_phase = "Failed"
    provider = _k8s_provider(module, _SandboxKubernetesConfig(create_timeout=5))
    with pytest.raises(SandboxProvisionError, match="terminated during provisioning"):
        await provider.create(principal=principal, policy=policy)
    assert cluster.pods == {}


@pytest.mark.asyncio
async def test_k8s_non_api_create_failure_cleans_up_the_network_policy(k8s_env, monkeypatch):
    # A connection-level failure (not an ApiException) from the pod create must still
    # delete the NetworkPolicy created just before it, or it is orphaned forever (destroy
    # and the sweep are keyed by pod, and this pod never existed).
    module, cluster = k8s_env
    principal, _ = _principal_policy()
    provider = _k8s_provider(module, _SandboxKubernetesConfig(network_policy=True))

    def broken_create(self, namespace, body):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(FakeCoreV1, "create_namespaced_pod", broken_create)
    with pytest.raises(SandboxProvisionError, match="connection reset"):
        await provider.create(principal=principal, policy=SandboxPolicy(network_egress="deny"))
    assert cluster.netpols == {} and cluster.netpol_deletes


@pytest.mark.asyncio
async def test_k8s_network_policy_gating(k8s_env):
    module, cluster = k8s_env
    principal, _ = _principal_policy()
    # Default posture: the provider maps nothing and the class capability stays honest.
    plain = _k8s_provider(module)
    assert plain.capabilities.policy_network is False
    await plain.create(principal=principal, policy=SandboxPolicy(network_egress="deny", strict=False))
    assert cluster.netpols == {}
    # network_policy: true flips the INSTANCE capability only, and maps deny/allowlist.
    asserted = _k8s_provider(module, _SandboxKubernetesConfig(network_policy=True))
    assert asserted.capabilities.policy_network is True
    assert module.KubernetesSandboxProvider.capabilities.policy_network is False  # class default untouched
    sandbox = await asserted.create(principal=principal, policy=SandboxPolicy(network_egress="deny"))
    pod_name = sandbox.id.split("/", 1)[1]
    netpol = cluster.netpols[("default", pod_name)]
    assert netpol["spec"]["podSelector"] == {"matchLabels": {"agentkernel.io/sandbox-name": pod_name}}
    assert netpol["spec"]["policyTypes"] == ["Egress"] and netpol["spec"]["egress"] == []
    await asserted.destroy(sandbox.id)
    assert ("default", pod_name) not in cluster.netpols and ("default", pod_name) not in cluster.pods
    # Allowlist: CIDRs become ipBlock rules; domains are unenforceable.
    listed = await asserted.create(principal=principal, policy=SandboxPolicy(network_egress="allowlist", network_allow=["10.0.0.0/8"]))
    listed_name = listed.id.split("/", 1)[1]
    assert cluster.netpols[("default", listed_name)]["spec"]["egress"] == [{"to": [{"ipBlock": {"cidr": "10.0.0.0/8"}}]}]
    before = len(cluster.pod_creates)
    with pytest.raises(SandboxPolicyError, match="example.com"):
        await asserted.create(principal=principal, policy=SandboxPolicy(network_egress="allowlist", network_allow=["example.com"]))
    assert len(cluster.pod_creates) == before  # rejected before any pod was created
    relaxed = await asserted.create(
        principal=principal, policy=SandboxPolicy(network_egress="allowlist", network_allow=["example.com", "10.1.0.0/16"], strict=False)
    )
    relaxed_name = relaxed.id.split("/", 1)[1]
    assert cluster.netpols[("default", relaxed_name)]["spec"]["egress"] == [{"to": [{"ipBlock": {"cidr": "10.1.0.0/16"}}]}]


@pytest.mark.asyncio
async def test_k8s_client_config_selection(k8s_env):
    module, cluster = k8s_env
    principal, policy = _principal_policy()
    explicit = _k8s_provider(module, _SandboxKubernetesConfig(kubeconfig="/tmp/kc"))
    await explicit.create(principal=principal, policy=policy)
    assert cluster.kubeconfig_loads == ["/tmp/kc"] and cluster.incluster_loads == []
    fallback = _k8s_provider(module)
    await fallback.create(principal=principal, policy=policy)
    assert cluster.incluster_loads == [True]  # in-cluster first when no kubeconfig is set


def test_factory_passes_profile_idle_timeout_to_kubernetes(k8s_env):
    profile = _SandboxProfileConfig(type="kubernetes", kubernetes=_SandboxKubernetesConfig(), idle_timeout=450)
    provider = SandboxProviderFactory._build("p", profile)
    assert provider._idle_timeout == 450


# --------------------------------------------------------------------------- #
# kubernetes user mode — RBAC impersonation (#503 iteration 8)
# --------------------------------------------------------------------------- #


def _user_principal(user="alice", groups=None):
    return SandboxPrincipal(mode="user", subject=user, credentials={"user": user, "groups": groups if groups is not None else ["devs"]})


@pytest.mark.asyncio
async def test_k8s_user_mode_impersonates_every_authorized_call_shape(k8s_env):
    module, cluster = k8s_env
    provider = _k8s_provider(module, _SandboxKubernetesConfig(network_policy=True))
    sandbox = await provider.create(principal=_user_principal(), policy=SandboxPolicy(network_egress="deny"))
    await sandbox.execute_code("print(1)")
    expected = {"Impersonate-User": "alice", "Impersonate-Group": "devs"}
    impersonated_ops = {op for op, headers in cluster.headers_log if headers == expected}
    assert {"create_pod", "read_pod", "create_netpol", "exec"} <= impersonated_ops
    # destroy stays the worker's own identity: disposal is platform-owned (no principal on the ABC,
    # and the idle sweep destroys without a user in context either).
    cluster.headers_log.clear()
    await provider.destroy(sandbox.id)
    assert [headers for op, headers in cluster.headers_log if op in ("delete_pod", "delete_netpol")] == [{}, {}]


@pytest.mark.asyncio
async def test_k8s_impersonating_clients_cached_per_subject(k8s_env):
    module, cluster = k8s_env
    provider = _k8s_provider(module)
    policy = SandboxPolicy()
    await provider.create(principal=_user_principal(), policy=policy)
    await provider.create(principal=_user_principal(), policy=policy)
    assert len(cluster.api_clients) == 1  # same (user, groups) subject reuses the client pair
    await provider.create(principal=_user_principal(user="bob"), policy=policy)
    assert len(cluster.api_clients) == 2


@pytest.mark.asyncio
async def test_k8s_agent_mode_sends_no_impersonation_headers(k8s_env):
    module, cluster = k8s_env
    provider = _k8s_provider(module)
    principal, policy = _principal_policy()
    sandbox = await provider.create(principal=principal, policy=policy)
    await sandbox.execute_command("echo hi")
    assert cluster.api_clients == []  # no impersonating client was ever built
    assert all(headers == {} for _, headers in cluster.headers_log)


@pytest.mark.asyncio
async def test_k8s_user_mode_fail_closed_rejections(k8s_env):
    module, cluster = k8s_env
    provider = _k8s_provider(module)
    with pytest.raises(SandboxPolicyError, match="at most one group"):
        await provider.create(
            principal=SandboxPrincipal(mode="user", subject="alice", credentials={"user": "alice", "groups": ["a", "b"]}),
            policy=SandboxPolicy(),
        )
    with pytest.raises(SandboxPolicyError, match="no user identity"):
        await provider.create(principal=SandboxPrincipal(mode="user", subject="", credentials={}), policy=SandboxPolicy())
    assert cluster.pod_creates == []  # both rejected before any API call


@pytest.mark.asyncio
async def test_k8s_worker_admits_user_mode_and_fails_closed_without_one(k8s_env, monkeypatch):
    # The worker's existing fail-closed check starts admitting identity.mode: user on this
    # provider purely because principal_user is now True; an agent-mode principal on a
    # user-mode profile still fails closed. No worker change.
    module, _cluster = k8s_env
    profile = _SandboxProfileConfig(type="kubernetes", kubernetes=_SandboxKubernetesConfig(), identity=_SandboxIdentityConfig(mode="user"))
    sandbox_cfg = _SandboxConfig(enabled=True, broker=_ExecutionBrokerConfig(flavor="embedded"), profiles={"default": profile})

    class _Cfg:
        sandbox = sandbox_cfg

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
    provider = _k8s_provider(module)
    core = BrokerWorkerCore()

    def _request(principal):
        session = SandboxSession(sandbox_session_id="s", profile="default", provider_type="kubernetes", created_at=1.0, last_used_at=1.0)
        return ExecutionRequest(
            task_id="t",
            operation="execute_code",
            payload={},
            profile="default",
            principal=principal,
            policy=SandboxPolicy(),
            sandbox_session=session,
            ak_session_id="",
            agent="a",
        )

    core._check_principal(provider, _request(_user_principal()))  # admitted
    with pytest.raises(SandboxPolicyError, match="requires user identity"):
        core._check_principal(provider, _request(SandboxPrincipal(mode="agent", subject="agent")))
