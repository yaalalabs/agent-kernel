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
    _SandboxBrokerConfig,
    _SandboxConfig,
    _SandboxDockerConfig,
    _SandboxLocalSubprocessConfig,
    _SandboxProfileConfig,
)
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.sandbox.errors import SandboxCapabilityError, SandboxGoneError, SandboxPolicyError, SandboxTimeoutError
from agentkernel.sandbox.factory import SandboxProviderFactory
from agentkernel.sandbox.manager import SandboxManager
from agentkernel.sandbox.model import SandboxPolicy, SandboxPrincipal
from agentkernel.sandbox.providers.local_subprocess import LocalSubprocessSandboxProvider
from agentkernel.sandbox.testing import SandboxProviderContract


@pytest.fixture(autouse=True)
def reset_singletons():
    AKConfig._reset()
    SandboxManager._reset()
    SandboxProviderFactory._reset()
    yield
    AKConfig._reset()
    SandboxManager._reset()
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
    cfg = _SandboxConfig(enabled=True, broker=_SandboxBrokerConfig(flavor="embedded"), profiles={"default": profile})

    class _Cfg:
        sandbox = cfg
        multimodal = None

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
    mgr = SandboxManager.get()
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
