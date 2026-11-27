import os
import socket
import stat
import subprocess
from pathlib import Path

import pytest
from mocks.host import mock_host

from ak_bench.errors import BenchConfigError, DeploymentLocked, ScriptFailed
from ak_bench.hosts.host import Deployment
from ak_bench.hosts.registry import HostRegistry
from ak_bench.results.common.layout import ResultsLayout
from ak_bench.run.deployment_folder import DeploymentFolder, ScriptEnv
from ak_bench.run.run_log import RunLog
from ak_bench.run.state import DeploymentLock, DeploymentState

DEPLOY_ROOT = Path(__file__).parent.parent / "mocks" / "deploy"
RUN_ID = "20261124T100000Z"
DEPLOYMENT_ID = f"{RUN_ID}-mock-async-complete"


@pytest.fixture
def layout(tmp_path) -> ResultsLayout:
    return ResultsLayout(tmp_path / "results", RUN_ID)


@pytest.fixture
def state(layout, monkeypatch) -> DeploymentState:
    monkeypatch.setitem(HostRegistry._BUILTINS, "mock", mock_host())
    path = layout.deployment_dir("mock", "mock", "async", "complete") / "state.json"
    data = {"run_id": RUN_ID, "deployment_id": DEPLOYMENT_ID, "host": "mock", "platform": "mock", "mode": "async", "message_type": "complete"}
    return DeploymentState.create(path, data | {"auth_secret": "ab" * 32, "load_steps": [1, 10], "lock": None})


@pytest.fixture
def run_log(layout) -> RunLog:
    return RunLog(layout.run_log(), "step")


def env_for(output: Path, mock_delays=None) -> ScriptEnv:
    return ScriptEnv(DEPLOYMENT_ID, "cd" * 32, mock_delays, {"max_cooldown_s": 60, "lambda_insights": True}, output)


def read_env(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text().splitlines())


def dead_pid() -> int:
    proc = subprocess.Popen(["true"])
    proc.wait()
    return proc.pid


def set_lock(state: DeploymentState, pid: int, host: str) -> dict:
    lock = {"pid": pid, "host": host, "command": "step steady 1", "since": "2026-11-24T10:00:00.000Z"}
    with state.update() as data:
        data["lock"] = lock
    return lock


# Results layout


def test_layout_paths_and_step_padding(layout):
    deployment_dir = layout.deployment_dir("aws", "ecs", "async", "complete")
    assert layout.run_log() == layout.root / RUN_ID / "run.log"
    assert deployment_dir == layout.root / RUN_ID / "aws" / "ecs" / "async" / "complete"
    assert layout.step_dir("aws", "ecs", "async", "complete", "steady", 1, [1, 10, 100, 1000]) == deployment_dir / "steady" / "step-0001"
    assert layout.step_dir("aws", "ecs", "async", "complete", "burst", 10, [1, 10]).name == "step-10"
    assert not layout.root.exists()  # paths only, nothing created


# Deployment folder


def test_check_names_missing_folder_and_script(tmp_path):
    with pytest.raises(BenchConfigError, match="nope-async-complete"):
        DeploymentFolder(tmp_path, "nope", "async", "complete").check()
    (tmp_path / "half-async-complete").mkdir()
    (tmp_path / "half-async-complete" / "deploy.sh").touch()
    with pytest.raises(BenchConfigError, match="destroy.sh"):
        DeploymentFolder(tmp_path, "half", "async", "complete").check()


def test_deploy_and_destroy_through_scripts(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_WS_URL", "ws://127.0.0.1:9999")
    monkeypatch.setenv("AK_BENCH_MOCK_AGENT_MIN_DELAY_S", "7")  # stale shell variable: must not reach the script
    folder = DeploymentFolder(DEPLOY_ROOT, "mock", "async", "complete")
    folder.check()

    deployment = folder.deploy(env_for(tmp_path / "out"))
    assert deployment.endpoint == "ws://127.0.0.1:9999"
    assert deployment.queues == {"input": {"name": "mock-in"}, "output": {"name": "mock-out"}}
    env = read_env(tmp_path / "out" / "deploy-env.txt")
    assert env == {
        "AK_BENCH_DEPLOYMENT_ID": DEPLOYMENT_ID,
        "AK_BENCH_AUTH_SECRET": "cd" * 32,
        "AK_BENCH_HOST_SETTINGS": '{"max_cooldown_s": 60, "lambda_insights": true}',
        "AK_BENCH_OUTPUT": str(tmp_path / "out"),
    }

    folder.destroy(env_for(tmp_path / "out"))
    assert (tmp_path / "out" / "destroy-ran.txt").read_text() == f"destroyed secret={'cd' * 32}\n"


def test_mock_delays_passed_only_for_mock_agent(tmp_path):
    DeploymentFolder(DEPLOY_ROOT, "mock", "async", "complete").deploy(env_for(tmp_path, (0.5, 2.0)))
    env = read_env(tmp_path / "deploy-env.txt")
    assert env["AK_BENCH_MOCK_AGENT_MIN_DELAY_S"] == "0.5"
    assert env["AK_BENCH_MOCK_AGENT_MAX_DELAY_S"] == "2.0"


def test_failing_scripts_raise_script_failed(tmp_path, monkeypatch):
    folder = DeploymentFolder(DEPLOY_ROOT, "mock", "async", "complete")
    monkeypatch.setenv("MOCK_DEPLOY_EXIT", "3")
    with pytest.raises(ScriptFailed, match=r"deploy.sh .* failed \(exit 3\)"):
        folder.deploy(env_for(tmp_path))
    monkeypatch.setenv("MOCK_DESTROY_EXIT", "4")
    with pytest.raises(ScriptFailed, match=r"destroy.sh .* failed \(exit 4\)"):
        folder.destroy(env_for(tmp_path))


def test_deploy_without_deployment_json_fails_even_with_a_leftover_one(tmp_path):
    folder_path = tmp_path / "bare-async-complete"
    folder_path.mkdir()
    (folder_path / "deploy.sh").write_text("exit 0\n")
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "deployment.json").write_text('{"endpoint": "stale"}')
    with pytest.raises(ScriptFailed, match="no readable .*deployment.json"):
        DeploymentFolder(tmp_path, "bare", "async", "complete").deploy(env_for(tmp_path / "out"))


def test_relative_output_dir_is_resolved_before_the_script_runs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    deployment = DeploymentFolder(DEPLOY_ROOT, "mock", "async", "complete").deploy(env_for(Path("results") / "out"))
    assert deployment.endpoint
    assert read_env(tmp_path / "results" / "out" / "deploy-env.txt")["AK_BENCH_OUTPUT"] == str(tmp_path / "results" / "out")


# State


def test_state_file_is_private_and_create_refuses_existing(state):
    assert stat.S_IMODE(state.path.stat().st_mode) == 0o600
    with pytest.raises(BenchConfigError, match="already exists"):
        DeploymentState.create(state.path, {})
    with state.update() as data:
        data["teardown_at"] = None
    assert stat.S_IMODE(state.path.stat().st_mode) == 0o600


def test_state_round_trips_deployment_and_run_info(state, tmp_path):
    deployment = DeploymentFolder(DEPLOY_ROOT, "mock", "async", "complete").deploy(env_for(tmp_path))
    with state.update() as data:
        data["deployment"] = deployment.to_json()
    assert state.deployment() == deployment
    assert state.run_info().deployment_id == DEPLOYMENT_ID
    assert isinstance(state.deployment(), Deployment)


def test_update_writes_nothing_when_body_raises(state):
    with pytest.raises(RuntimeError), state.update() as data:
        data["load_steps"] = [99]
        raise RuntimeError
    assert state.read()["load_steps"] == [1, 10]


def test_locate_finds_state_from_deployment_id(state, layout):
    assert DeploymentState.locate(layout.root, DEPLOYMENT_ID).path == state.path
    with pytest.raises(BenchConfigError, match="not found"):
        DeploymentState.locate(layout.root, "20991231T000000Z-mock-async-complete")
    with pytest.raises(BenchConfigError, match="<run-id>-<host>-<mode>-<message-type>"):
        DeploymentState.locate(layout.root, "bad-id")


# Deployment lock


def test_acquire_and_release(state, run_log):
    lock = DeploymentLock(state, run_log, "step steady 1")
    lock.acquire()
    held = state.read()["lock"]
    assert (held["pid"], held["host"], held["command"]) == (os.getpid(), socket.gethostname(), "step steady 1")
    lock.release()
    assert state.read()["lock"] is None


def test_release_leaves_another_holders_lock(state, run_log):
    other = set_lock(state, os.getpid(), "other-box")
    DeploymentLock(state, run_log, "step steady 1").release()
    assert state.read()["lock"] == other


def test_live_local_lock_refused(state, run_log):
    set_lock(state, os.getppid(), socket.gethostname())  # another live process on this machine
    with pytest.raises(DeploymentLocked, match=f"pid {os.getppid()} on {socket.gethostname()} since"):
        DeploymentLock(state, run_log, "step burst 1").acquire()


def test_other_machine_lock_refused(state, run_log):
    set_lock(state, dead_pid(), "other-box")
    with pytest.raises(DeploymentLocked, match="on other-box since 2026-11-24T10:00:00.000Z"):
        DeploymentLock(state, run_log, "step steady 1").acquire()


def test_stale_local_lock_taken_over_with_warning(state, run_log):
    pid = dead_pid()
    set_lock(state, pid, socket.gethostname())
    DeploymentLock(state, run_log, "step steady 1").acquire()
    assert state.read()["lock"]["pid"] == os.getpid()
    assert f"WARNING step took over stale deployment lock of pid {pid} since 2026-11-24T10:00:00.000Z" in run_log.path.read_text()


def test_force_unlock_with_yes_clears_and_logs(state, run_log, capsys):
    set_lock(state, 4242, "other-box")
    DeploymentLock(state, run_log, "step --force-unlock").force_unlock(lambda _: True)
    assert state.read()["lock"] is None
    assert "deployment lock held by pid 4242 on other-box since 2026-11-24T10:00:00.000Z (step steady 1)" in capsys.readouterr().out
    assert "WARNING step force-unlocked deployment lock held by pid 4242 on other-box" in run_log.path.read_text()


def test_force_unlock_declined_keeps_lock(state, run_log, capsys):
    held = set_lock(state, 4242, "other-box")
    DeploymentLock(state, run_log, "step --force-unlock").force_unlock(lambda _: False)
    assert state.read()["lock"] == held
    assert "deployment lock kept" in capsys.readouterr().out
    assert not run_log.path.exists()


def test_force_unlock_refuses_live_local_lock(state, run_log):
    set_lock(state, os.getpid(), socket.gethostname())
    with pytest.raises(DeploymentLocked, match="stop it instead"):
        DeploymentLock(state, run_log, "step --force-unlock").force_unlock(lambda _: True)


def test_force_unlock_without_lock_says_so(state, run_log, capsys):
    DeploymentLock(state, run_log, "step --force-unlock").force_unlock(lambda _: pytest.fail("must not ask"))
    assert "no deployment lock held" in capsys.readouterr().out


def test_force_unlock_refuses_if_lock_changed_while_confirming(state, run_log):
    set_lock(state, 4242, "other-box")

    def confirm(_):
        set_lock(state, 5555, "third-box")
        return True

    with pytest.raises(DeploymentLocked, match="changed while confirming"):
        DeploymentLock(state, run_log, "step --force-unlock").force_unlock(confirm)
    assert state.read()["lock"]["pid"] == 5555
