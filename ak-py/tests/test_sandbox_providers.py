"""First-party sandbox provider tests.

``local_subprocess`` runs real subprocesses (``sys.executable`` / bash) against real temp
directories, including the public ``SandboxProviderContract`` suite. ``docker`` runs
against a mocked Docker SDK (no daemon): call shapes, policy mapping arguments, and
``to_thread`` usage are asserted per spec §Testing.
"""

import asyncio
import importlib
import io
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
    _SandboxLocalSubprocessConfig,
    _SandboxProfileConfig,
)
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.sandbox.errors import SandboxCapabilityError, SandboxGoneError, SandboxPolicyError, SandboxTimeoutError
from agentkernel.sandbox.factory import SandboxProviderFactory
from agentkernel.sandbox.manager import ExecutionManager
from agentkernel.sandbox.model import SandboxPolicy, SandboxPrincipal
from agentkernel.sandbox.providers.local_subprocess import LocalSubprocessSandboxProvider
from agentkernel.sandbox.testing import SandboxProviderContract


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
async def test_ssm_user_mode_assumes_role_and_runs_as(ssm_env):
    module, fake = ssm_env
    provider = _ssm_provider(module)
    principal = SandboxPrincipal(
        mode="user",
        subject="alice",
        credentials={"role_arn": "arn:aws:iam::1:role/dev", "run_as": "alice"},
    )
    sandbox = await provider.attach("i-abc123", principal=principal, policy=SandboxPolicy())

    assert fake.sts.assume_calls[0]["RoleArn"] == "arn:aws:iam::1:role/dev"
    assert fake.sts.assume_calls[0]["RoleSessionName"].startswith("ak-sandbox-alice")
    ssm_calls = [kwargs for service, kwargs in fake.client_calls if service == "ssm"]
    assert ssm_calls[-1]["aws_access_key_id"] == "AKIA-TEST"  # client built from the assumed role
    assert ssm_calls[-1]["aws_session_token"] == "token"

    await sandbox.execute_command("whoami")
    command = fake.ssm.send_calls[0]["Parameters"]["commands"][0]
    assert command.startswith("sudo -n -u alice sh -c ")  # RunAs realized as a sudo prefix
    assert "whoami" in command


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

            def code_run(code, params=None, timeout=None):
                outer.code_calls.append((code, params, timeout))
                outer.exec_threads.append(threading.current_thread())
                return types.SimpleNamespace(exit_code=outer.next_exit_code, result=outer.next_result)

            def exec_(command, cwd=None, env=None, timeout=None):
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
