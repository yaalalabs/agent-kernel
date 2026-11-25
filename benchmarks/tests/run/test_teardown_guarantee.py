import json
import os
import socket
from pathlib import Path

import pytest
import yaml

from ak_bench.cli import BenchCli
from ak_bench.config import BenchConfig
from ak_bench.errors import ScriptFailed
from ak_bench.results.common.layout import ResultsLayout
from ak_bench.run.commands import Deploy, Finish, Run, Step
from ak_bench.run.deployment_folder import DeploymentFolder
from ak_bench.run.step_runner import StepRunner

RUN_ID = "20261124T100000Z"
DEPLOYMENT_ID = f"{RUN_ID}-mock-async-complete"


def destroy_runs(deployment_dir) -> int:
    path = deployment_dir / "destroy-ran.txt"
    return len(path.read_text().splitlines()) if path.exists() else 0


def run_log_of(deployment_dir) -> str:
    return (deployment_dir.parents[3] / "run.log").read_text()


def failing_step(error: BaseException):
    def execute(self, *args):
        raise error

    return execute


@pytest.mark.parametrize("error", [RuntimeError("step broke"), KeyboardInterrupt()])
def test_run_tears_down_when_a_step_fails_or_is_interrupted(bench, monkeypatch, error):
    monkeypatch.setattr(Step, "execute", failing_step(error))
    with pytest.raises(type(error)):
        bench(Run).execute(None, None, None, None)
    (out,) = bench.deployment_dirs()
    assert destroy_runs(out) == 1
    assert json.loads((out / "state.json").read_text())["teardown_at"]


def test_interrupted_step_releases_the_lock_and_run_still_tears_down(bench, monkeypatch):
    async def interrupted(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(StepRunner, "run", interrupted)  # the real Step command, interrupted inside its step
    with pytest.raises(KeyboardInterrupt):
        bench(Run).execute(None, None, None, None)
    (out,) = bench.deployment_dirs()
    state = json.loads((out / "state.json").read_text())
    assert state["lock"] is None and state["teardown_at"] and destroy_runs(out) == 1


def test_lock_left_by_this_process_does_not_block_teardown(bench):
    bench(Deploy).execute("mock", "async", "complete", RUN_ID)
    path = bench.deployment_dir() / "state.json"
    data = json.loads(path.read_text())
    data["lock"] = {"pid": os.getpid(), "host": socket.gethostname(), "command": "step steady 1", "since": "2026-11-24T10:00:00.000Z"}
    path.write_text(json.dumps(data))  # as if Ctrl-C cut the step's release short
    bench(Finish).execute(DEPLOYMENT_ID)
    assert bench.state()["teardown_at"] and bench.state()["lock"] is None


def test_second_interrupt_during_finish_skips_teardown_and_logs_it(bench, monkeypatch):
    monkeypatch.setattr(Step, "execute", failing_step(KeyboardInterrupt()))
    monkeypatch.setattr(Finish, "execute", failing_step(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        bench(Run).execute(None, None, None, None)
    (out,) = bench.deployment_dirs()
    assert destroy_runs(out) == 0
    assert f"ERROR run teardown skipped by a second Ctrl-C: {out.parents[3].name}-mock-async-complete may be left running" in run_log_of(out)


def test_step_error_wins_over_a_failed_teardown(bench, monkeypatch):
    monkeypatch.setattr(Step, "execute", failing_step(RuntimeError("step broke")))
    monkeypatch.setenv("MOCK_DESTROY_EXIT", "4")
    with pytest.raises(RuntimeError, match="step broke"):
        bench(Run).execute(None, None, None, None)
    (out,) = bench.deployment_dirs()
    assert "resources may be left running" in run_log_of(out)


def test_deploy_failure_runs_destroy(bench, monkeypatch):
    monkeypatch.setenv("MOCK_DEPLOY_EXIT", "3")
    with pytest.raises(ScriptFailed, match=r"deploy.sh .* \(exit 3\)"):
        bench(Deploy).execute("mock", "async", "complete", RUN_ID)
    out = bench.deployment_dir()
    assert destroy_runs(out) == 1
    assert "ERROR deploy" in bench.run_log()
    assert json.loads((out / "state.json").read_text())["teardown_at"]


def test_interrupt_during_deploy_runs_destroy(bench, monkeypatch):
    monkeypatch.setattr(DeploymentFolder, "deploy", failing_step(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        bench(Deploy).execute("mock", "async", "complete", RUN_ID)
    assert destroy_runs(bench.deployment_dir()) == 1 and bench.state()["teardown_at"]


def test_destroy_failure_is_logged_and_finish_can_run_again(bench, monkeypatch):
    bench(Deploy).execute("mock", "async", "complete", RUN_ID)
    monkeypatch.setenv("MOCK_DESTROY_EXIT", "4")
    with pytest.raises(ScriptFailed, match=r"\(exit 4\)"):
        bench(Finish).execute(DEPLOYMENT_ID)
    state = bench.state()
    assert state["teardown_at"] is None and state["auth_secret"]  # still deployed as far as the harness knows
    assert "ERROR finish destroy.sh" in bench.run_log() and "resources may be left running" in bench.run_log()

    monkeypatch.delenv("MOCK_DESTROY_EXIT")
    bench(Finish).execute(DEPLOYMENT_ID)
    assert destroy_runs(bench.deployment_dir()) == 2 and bench.state()["teardown_at"]


@pytest.fixture
def cli(bench, tmp_path):
    """BenchCli args for the mock host: a config file with the bench config, and the mock deployment folder."""
    path = tmp_path / "ak-bench.yaml"
    path.write_text(yaml.safe_dump(bench.config.model_dump(mode="json", exclude_none=True)))
    BenchConfig._reset()
    yield ["--config", str(path), "--results-dir", str(bench.results), "--deploy-root", str(Path(__file__).parent.parent / "mocks" / "deploy")]
    BenchConfig._reset()


def test_cli_exit_codes(cli, bench, monkeypatch):
    monkeypatch.setenv("MOCK_DEPLOY_EXIT", "3")
    assert BenchCli().run([*cli, "deploy", "--host", "mock", "--mode", "async", "--message-type", "complete", "--run-id", RUN_ID]) == 1
    assert destroy_runs(bench.deployment_dir()) == 1

    monkeypatch.setattr(Step, "execute", failing_step(KeyboardInterrupt()))
    monkeypatch.delenv("MOCK_DEPLOY_EXIT")
    assert BenchCli().run([*cli, "run"]) == 130
    assert all(json.loads((d / "state.json").read_text())["teardown_at"] for d in bench.deployment_dirs())
    assert ResultsLayout(bench.results, RUN_ID).run_log().exists()
