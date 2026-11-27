import asyncio
import json
import os
import socket

import pytest
from mocks.ws_server import MockWsServer

from ak_bench.config import FetchersConfig, HostSettings, MockAgentConfig
from ak_bench.errors import BenchConfigError, DeploymentLocked, StepRefused
from ak_bench.run.commands import Deploy, Finish, Plot, PostRun, Run, Step

RUN_ID = "20261124T100000Z"
DEPLOYMENT_ID = f"{RUN_ID}-mock-async-complete"
SECRET = "ab" * 32
STEP_FILES = ["per-request.csv", "per-time-window.csv", "step-metadata.json"]
STEADY_GRAPHS = ["01-stage-times.png", "02-stage-breakdown.png", "03-timeline.png", "04-every-request.png", "05-resource-usage.png"]


def env_of(deployment_dir) -> dict[str, str]:
    return dict(line.split("=", 1) for line in (deployment_dir / "deploy-env.txt").read_text().splitlines())


def deploy(bench) -> str:
    return bench(Deploy).execute("mock", "async", "complete", RUN_ID)


@pytest.mark.asyncio
async def test_deploy_step_plot_finish_post_run(bench, monkeypatch, capsys):
    async with MockWsServer(SECRET, delay_s=0.02) as server:
        monkeypatch.setenv("MOCK_WS_URL", server.url)
        assert deploy(bench) == DEPLOYMENT_ID
        await asyncio.to_thread(bench(Step).execute, DEPLOYMENT_ID, "steady", 1, False)
        await asyncio.to_thread(bench(Step).execute, DEPLOYMENT_ID, "burst", 2, False)
    bench(Plot).execute(DEPLOYMENT_ID, None)
    assert bench(Finish).execute(DEPLOYMENT_ID) is True
    bench(PostRun).execute(None, RUN_ID)

    out, printed = bench.deployment_dir(), capsys.readouterr().out
    assert DEPLOYMENT_ID in printed and "post-run needed: cost" in printed
    for test_type, step, graphs in (
        ("steady", "step-1", STEADY_GRAPHS),
        ("burst", "step-2", [g for g in STEADY_GRAPHS if g != "04-every-request.png"]),
    ):
        step_dir = out / test_type / step
        assert all((step_dir / f).exists() for f in STEP_FILES)
        assert sorted(p.name for p in (step_dir / "graphs").iterdir()) == graphs
    assert (out / "run-metadata.json").exists() and (out / "cost.csv").exists()
    assert (out / "graphs" / "cost-by-service.png").exists()
    assert " ERROR " not in bench.run_log()

    # Script env: the contract variables, no mock delays without mock_agent
    env = env_of(out)
    assert env["AK_BENCH_DEPLOYMENT_ID"] == DEPLOYMENT_ID and env["AK_BENCH_AUTH_SECRET"] == SECRET
    assert env["AK_BENCH_OUTPUT"] == str(out.resolve()) and json.loads(env["AK_BENCH_HOST_SETTINGS"]) == {}
    assert not any(k.startswith("AK_BENCH_MOCK_AGENT") for k in env)

    # state.json: the deployment round-trips unchanged, the steps are recorded, the secret is gone after finish
    state = bench.state()
    assert state["deployment"] == json.loads((out / "deployment.json").read_text())
    assert set(state["steps"]) == {"steady/1", "burst/2"} and state["lock"] is None
    assert state["teardown_at"] and "auth_secret" not in state
    assert (out / "destroy-ran.txt").read_text() == f"destroyed secret={SECRET}\n"


def test_mock_delays_and_host_settings_go_to_the_scripts(bench):
    bench.config.mock_agent = MockAgentConfig(min_delay=0.1, max_delay=0.2)
    bench.config.host_settings["mock"] = HostSettings(max_cooldown_s=60, lambda_insights=True)
    deploy(bench)
    env = env_of(bench.deployment_dir())
    assert env["AK_BENCH_MOCK_AGENT_MIN_DELAY_S"] == "0.1" and env["AK_BENCH_MOCK_AGENT_MAX_DELAY_S"] == "0.2"
    assert json.loads(env["AK_BENCH_HOST_SETTINGS"]) == {"lambda_insights": True}  # max_cooldown_s stays with the harness
    assert json.loads((bench.deployment_dir() / "run-metadata.json").read_text())["agent"] == "mock"


def test_finish_says_when_post_run_is_not_needed(bench, capsys):
    bench.host.fetchers.after_teardown.clear()
    deploy(bench)
    assert bench(Finish).execute(DEPLOYMENT_ID) is False
    assert "post-run not needed" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_existing_step_folder_needs_replace(bench, monkeypatch):
    async with MockWsServer(SECRET) as server:
        monkeypatch.setenv("MOCK_WS_URL", server.url)
        deploy(bench)
        await asyncio.to_thread(bench(Step).execute, DEPLOYMENT_ID, "burst", 1, False)
        first = bench.state()["steps"]["burst/1"]
        marker = bench.deployment_dir() / "burst" / "step-1" / "marker"
        marker.touch()

        with pytest.raises(StepRefused, match="--replace"):
            bench(Step).execute(DEPLOYMENT_ID, "burst", 1, False)
        assert marker.exists()

        await asyncio.to_thread(bench(Step).execute, DEPLOYMENT_ID, "burst", 1, True)
    assert not marker.exists() and (marker.parent / "per-request.csv").exists()
    assert bench.state()["steps"]["burst/1"]["started"] > first["started"]
    assert bench.state()["lock"] is None


def test_step_refusals(bench):
    deploy(bench)
    with pytest.raises(StepRefused, match=r"step 7 is not a load step .* \[1, 2\]"):
        bench(Step).execute(DEPLOYMENT_ID, "steady", 7, False)

    state = bench.deployment_dir() / "state.json"
    data = json.loads(state.read_text())
    data["lock"] = {"pid": os.getppid(), "host": socket.gethostname(), "command": "step steady 1", "since": "2026-11-24T10:00:00.000Z"}
    state.write_text(json.dumps(data))
    with pytest.raises(DeploymentLocked, match=f"deployment lock held by pid {os.getppid()}"):
        bench(Step).execute(DEPLOYMENT_ID, "steady", 1, False)
    assert not (bench.deployment_dir() / "steady").exists()

    data["lock"] = None
    state.write_text(json.dumps(data))
    bench(Finish).execute(DEPLOYMENT_ID)
    with pytest.raises(StepRefused, match="was torn down"):
        bench(Step).execute(DEPLOYMENT_ID, "steady", 1, False)


@pytest.mark.parametrize(
    "command",
    [
        lambda bench: bench(Step).execute(DEPLOYMENT_ID, "steady", 1, False),
        lambda bench: bench(Plot).execute(DEPLOYMENT_ID, None),
        lambda bench: bench(Plot).execute(None, RUN_ID),
        lambda bench: bench(Finish).execute(DEPLOYMENT_ID),
        lambda bench: bench(PostRun).execute(DEPLOYMENT_ID, None),
    ],
    ids=["step", "plot", "plot-run", "finish", "post-run"],
)
def test_every_command_is_refused_while_another_holds_the_deployment(bench, command):
    deploy(bench)
    state = bench.deployment_dir() / "state.json"
    data = json.loads(state.read_text())
    data["teardown_at"] = "2026-11-24T11:00:00.000Z"  # so post-run gets as far as the lock
    data["lock"] = {"pid": os.getppid(), "host": socket.gethostname(), "command": "step steady 1", "since": "2026-11-24T10:00:00.000Z"}
    state.write_text(json.dumps(data))
    with pytest.raises(DeploymentLocked, match=r"deployment lock held by .* \(step steady 1\)"):
        command(bench)
    assert not (bench.deployment_dir() / "destroy-ran.txt").exists() and json.loads(state.read_text())["lock"] == data["lock"]


def test_lock_is_held_while_a_command_runs_and_released_after(bench, monkeypatch):
    seen = []
    monkeypatch.setattr(Finish, "_finish", lambda self, state, run_log: seen.append(state.read()["lock"]["command"]))
    deploy(bench)
    assert bench.state()["lock"] is None  # deploy released it
    bench(Finish).execute(DEPLOYMENT_ID)
    assert seen == ["finish"] and bench.state()["lock"] is None


def test_post_run_before_finish_is_refused(bench):
    deploy(bench)
    with pytest.raises(StepRefused, match="run finish first"):
        bench(PostRun).execute(DEPLOYMENT_ID, None)


def test_run_with_nothing_selected_is_refused(bench, monkeypatch):
    monkeypatch.setattr(bench.config, "hosts", None)
    monkeypatch.setattr("ak_bench.hosts.registry.HostRegistry._BUILTINS", {})
    with pytest.raises(BenchConfigError, match="nothing to run"):
        bench(Run).execute(None, None, None, None)


def test_run_refuses_unknown_steps_before_any_deploy(bench):
    with pytest.raises(BenchConfigError, match=r"--steps 7 not in load_steps \[1, 2\]"):
        bench(Run).execute(None, None, None, [7])
    assert not bench.results.exists()


def test_unknown_fetcher_name_and_missing_folder_refused_before_any_script(bench, tmp_path):
    bench.config.fetchers = FetchersConfig.model_validate({"default": {"poll_interval_s": 1}, "aws-ecs": {"poll_interval_s": 1}})
    with pytest.raises(BenchConfigError, match="fetchers.aws-ecs"):
        deploy(bench)
    with pytest.raises(BenchConfigError, match="fetchers.aws-ecs"):
        bench(Run).execute(None, None, None, None)

    bench.config.fetchers = FetchersConfig.model_validate({"default": {"poll_interval_s": 1}})
    with pytest.raises(BenchConfigError, match="mock-async-complete"):
        bench(Deploy, deploy_root=tmp_path / "empty").execute("mock", "async", "complete", None)
    assert not bench.results.exists()


def test_same_combination_twice_in_a_run_is_refused(bench):
    deploy(bench)
    with pytest.raises(BenchConfigError, match="already exists"):
        deploy(bench)
    with pytest.raises(BenchConfigError, match="must match"):
        bench(Deploy).execute("mock", "async", "complete", "2026-11-24")


def test_run_order_and_teardown(bench, monkeypatch):
    calls = []
    monkeypatch.setattr(Step, "execute", lambda self, deployment_id, test_type, n, replace: calls.append((test_type, n)))
    bench(Run).execute(None, None, None, None)
    assert calls == [("steady", 1), ("burst", 1), ("steady", 2), ("burst", 2)]
    (out,) = bench.deployment_dirs()
    assert json.loads((out / "state.json").read_text())["teardown_at"]


def test_repeated_run_flags_deploy_once(bench, monkeypatch):
    monkeypatch.setattr(Step, "execute", lambda *args: None)
    bench(Run).execute(["mock", "mock"], None, None, None)
    assert len(bench.deployment_dirs()) == 1


def test_force_unlock_prompt_closed_keeps_the_lock(bench, monkeypatch):
    deploy(bench)
    state = bench.deployment_dir() / "state.json"
    data = json.loads(state.read_text())
    data["lock"] = {"pid": 1, "host": "other-machine", "command": "step steady 1", "since": "2026-11-24T10:00:00.000Z"}
    state.write_text(json.dumps(data))

    def closed(prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", closed)
    bench(Step).force_unlock(DEPLOYMENT_ID, yes=False)
    assert bench.state()["lock"]["host"] == "other-machine"


def test_run_steps_subset(bench, monkeypatch):
    calls = []
    monkeypatch.setattr(Step, "execute", lambda self, deployment_id, test_type, n, replace: calls.append((test_type, n)))
    bench.config.test_types = ["burst"]
    bench(Run).execute(["mock"], ["async"], ["complete"], [2])
    assert calls == [("burst", 2)]
