import json
from pathlib import Path

import pytest
import yaml

from ak_bench.cli import BenchCli
from ak_bench.config import BenchConfig
from ak_bench.errors import ScriptFailed
from ak_bench.run.commands import Deploy, Finish, Run, Step
from ak_bench.run.deployment_folder import DeploymentFolder
from ak_bench.run.step_runner import StepRunner

RUN_ID = "20261124T100000Z"
DEPLOYMENT_ID = f"{RUN_ID}-mock-async-complete"
SECRET = "ab" * 32


def destroy_runs(deployment_dir) -> int:
    path = deployment_dir / "destroy-ran.txt"
    return len(path.read_text().splitlines()) if path.exists() else 0


def run_log_of(deployment_dir) -> str:
    return (deployment_dir.parents[3] / "run.log").read_text()


def failing_step(error: BaseException):
    def execute(self, *args):
        raise error

    return execute


def test_run_tears_down_when_a_step_fails(bench, monkeypatch):
    monkeypatch.setattr(Step, "execute", failing_step(RuntimeError("step broke")))
    with pytest.raises(RuntimeError):
        bench(Run).execute(None, None, None, None)
    (out,) = bench.deployment_dirs()
    assert destroy_runs(out) == 1
    assert json.loads((out / "state.json").read_text())["teardown_at"]


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


def test_cli_exit_code_on_failed_deploy(cli, bench, monkeypatch):
    monkeypatch.setenv("MOCK_DEPLOY_EXIT", "3")
    assert BenchCli().run([*cli, "deploy", "--host", "mock", "--mode", "async", "--message-type", "complete", "--run-id", RUN_ID]) == 1
    assert destroy_runs(bench.deployment_dir()) == 1


def interrupted(*args):
    raise KeyboardInterrupt


async def interrupted_step(*args):
    raise KeyboardInterrupt


def assert_left_deployed(out) -> None:
    """Ctrl-C tore nothing down: no destroy.sh, lock released, teardown_at unset, and the run log says what to do."""
    state = json.loads((out / "state.json").read_text())
    deployment_id = state["deployment_id"]
    assert destroy_runs(out) == 0 and state["lock"] is None and state["teardown_at"] is None
    warnings = [line for line in run_log_of(out).splitlines() if " WARNING " in line and "interrupted" in line]
    assert len(warnings) == 1
    assert deployment_id in warnings[0] and f"ak-bench finish --deployment {deployment_id}" in warnings[0]


def test_interrupt_during_deploy_tears_nothing_down(cli, bench, monkeypatch):
    monkeypatch.setattr(DeploymentFolder, "deploy", interrupted)
    assert BenchCli().run([*cli, "deploy", "--host", "mock", "--mode", "async", "--message-type", "complete", "--run-id", RUN_ID]) == 130
    assert_left_deployed(bench.deployment_dir())
    state = bench.state()
    assert state["deployment"] is None and state["auth_secret"] and state["deployment_id"] == DEPLOYMENT_ID


def test_interrupt_during_step_tears_nothing_down(cli, bench, monkeypatch):
    bench(Deploy).execute("mock", "async", "complete", RUN_ID)
    monkeypatch.setattr(StepRunner, "run", interrupted_step)  # the real Step command, interrupted inside its step
    assert BenchCli().run([*cli, "step", "--deployment", DEPLOYMENT_ID, "--test-type", "steady", "--step", str(bench.config.load_steps[0])]) == 130
    assert_left_deployed(bench.deployment_dir())


def test_interrupt_during_run_stops_without_finish(cli, bench, monkeypatch):
    monkeypatch.setattr(StepRunner, "run", interrupted_step)
    monkeypatch.setattr(Finish, "execute", lambda *args: pytest.fail("finish must not run on Ctrl-C"))
    assert BenchCli().run([*cli, "run"]) == 130
    (out,) = bench.deployment_dirs()
    assert_left_deployed(out)


def test_finish_tears_down_a_deployment_whose_deploy_was_interrupted(bench, monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(DeploymentFolder, "deploy", interrupted)
        with pytest.raises(KeyboardInterrupt):
            bench(Deploy).execute("mock", "async", "complete", RUN_ID)
    bench(Finish).execute(DEPLOYMENT_ID)
    out = bench.deployment_dir()
    assert destroy_runs(out) == 1 and bench.state()["teardown_at"] and "auth_secret" not in bench.state()
    assert (out / "destroy-ran.txt").read_text() == f"destroyed secret={SECRET}\n"  # the secret deploy.sh got
