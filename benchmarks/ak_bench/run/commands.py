import asyncio
import re
import secrets
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ak_bench.config import BenchConfig, TestType
from ak_bench.errors import BenchConfigError, ScriptFailed, StepRefused
from ak_bench.hosts.host import Deployment, Host
from ak_bench.hosts.registry import HostRegistry
from ak_bench.load.driver.factory import DriverFactory
from ak_bench.results.common.keyed_csv import KeyedCsv
from ak_bench.results.common.layout import ResultsLayout
from ak_bench.results.csv.per_request import PerRequestWriter
from ak_bench.results.csv.per_window import PerWindowWriter
from ak_bench.results.graphs.cost_graph import CostReport
from ak_bench.results.graphs.step_graphs import StepPlots
from ak_bench.results.metadata import RunMetadataWriter, StepMetadataWriter
from ak_bench.run.deployment_folder import DeploymentFolder, ScriptEnv
from ak_bench.run.fetcher_invoker import FetcherInvoker
from ak_bench.run.run_log import RunLog
from ak_bench.run.state import DeploymentLock, DeploymentState
from ak_bench.run.step_runner import StepRunner


class Command:
    """Shared by every command: the loaded config, the results root and the deployment-folder root."""

    def __init__(self, config: BenchConfig, results_root: Path, deploy_root: Path):
        self.config = config
        self.results_root = Path(results_root)
        self.deploy_root = Path(deploy_root)

    def _run_log(self, run_id: str, command: str) -> RunLog:
        return RunLog(ResultsLayout(self.results_root, run_id).run_log(), command)

    def _states(self, deployment_id: str | None, run_id: str | None) -> list[DeploymentState]:
        """One deployment, or every deployment of a run."""
        if deployment_id:
            return [DeploymentState.locate(self.results_root, deployment_id)]
        run_dir = ResultsLayout(self.results_root, run_id).run_dir()
        states = [DeploymentState(p) for p in sorted(run_dir.glob("*/*/*/*/state.json"))]
        if not states:
            raise BenchConfigError(f"no deployments under {run_dir}")
        return states

    @staticmethod
    def _deployment(data: dict[str, Any]) -> Deployment:
        """The saved deployment; an empty one when deploy.sh never wrote one (fetchers still get the deployment id)."""
        return Deployment.from_json(data["deployment"]) if data.get("deployment") else Deployment("", {}, {}, {}, {})

    @staticmethod
    def _time(value: str) -> datetime:
        return datetime.fromisoformat(value)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @classmethod
    def _new_run_id(cls) -> str:
        """No '-' in it, so a deployment id splits into run id, host, mode and message type (DeploymentState.locate)."""
        return cls._now().strftime("%Y%m%dT%H%M%SZ")

    def _destroy(self, state: DeploymentState, run_log: RunLog) -> None:
        """Runs destroy.sh with the deploy inputs; on success records teardown_at and drops the auth secret."""
        data = state.read()
        delays = data.get("mock_delays")
        env = ScriptEnv(
            data["deployment_id"],
            data.get("auth_secret") or "",
            tuple(delays) if delays else None,
            data.get("host_settings") or {},
            state.path.parent,
        )
        try:
            DeploymentFolder(self.deploy_root, data["host"], data["mode"], data["message_type"]).destroy(env)
        except ScriptFailed as e:
            run_log.error(f"{e}: resources may be left running")
            raise
        with state.update() as d:
            d["teardown_at"] = KeyedCsv.cell(self._now())
            d.pop("auth_secret", None)


class Deploy(Command):
    RUN_ID = re.compile(r"[A-Za-z0-9_]+")

    def check(self, host: str, mode: str, message_type: str) -> tuple[Host, tuple[float, float] | None, DeploymentFolder]:
        """Checks 1-4, before any script runs (`run` calls this for every combination first)."""
        host_obj = HostRegistry.get(host)
        DriverFactory.driver_class(mode, message_type)
        self.config.fetchers.check_names({f.name for f in host_obj.fetchers.all()})
        delays = self.config.mock_agent.delays() if self.config.mock_agent else None
        folder = DeploymentFolder(self.deploy_root, host, mode, message_type)
        folder.check()
        return host_obj, delays, folder

    def execute(self, host: str, mode: str, message_type: str, run_id: str | None) -> str:
        host_obj, delays, folder = self.check(host, mode, message_type)
        if run_id is not None and not self.RUN_ID.fullmatch(run_id):
            raise BenchConfigError(f"--run-id '{run_id}' must match ^[A-Za-z0-9_]+$")
        run_id = run_id or self._new_run_id()
        deployment_id = f"{run_id}-{host}-{mode}-{message_type}"
        deployment_dir = ResultsLayout(self.results_root, run_id).deployment_dir(host_obj.platform, host, mode, message_type)
        settings = self.config.host_settings.get(host)
        host_settings = dict(settings.model_extra or {}) if settings else {}  # max_cooldown_s is the harness's, not deploy.sh's
        started = self._now()
        state = DeploymentState.create(  # refuses a host x mode x message type already deployed in this run
            deployment_dir / "state.json",
            {
                "run_id": run_id,
                "deployment_id": deployment_id,
                "host": host,
                "platform": host_obj.platform,
                "mode": mode,
                "message_type": message_type,
                "deployment": None,
                "auth_secret": secrets.token_hex(32),
                "load_steps": self.config.load_steps,
                # Saved so destroy.sh gets the same inputs even if ak-bench.yaml changed since
                "mock_delays": delays,
                "host_settings": host_settings,
                "deploy_started": KeyedCsv.cell(started),
                "deploy_finished": None,
                "steps": {},
                "lock": None,
                "teardown_at": None,
            },
        )
        run_log = self._run_log(run_id, "deploy")
        env = ScriptEnv(deployment_id, state.read()["auth_secret"], delays, host_settings, deployment_dir)
        with DeploymentLock(state, run_log, "deploy"):
            self._deploy(state, folder, env, run_log, started, delays)
        run_log.info(f"deployed {deployment_id}")
        print(deployment_id)
        return deployment_id

    def _deploy(
        self, state: DeploymentState, folder: DeploymentFolder, env: ScriptEnv, run_log: RunLog, started: datetime, delays: tuple[float, float] | None
    ) -> None:
        try:
            deployment = folder.deploy(env)
            with state.update() as d:
                d["deployment"] = deployment.to_json()
                d["deploy_finished"] = KeyedCsv.cell(self._now())
            RunMetadataWriter().write(state.path.parent, state.run_info(), started, deployment, delays)
        except Exception as e:  # not on Ctrl-C: state.json already holds what `finish` needs to run destroy.sh
            run_log.error(f"deploy failed: {type(e).__name__}: {e}; running destroy.sh for what it may have created")
            try:
                self._destroy(state, run_log)
            except ScriptFailed:
                pass  # logged by _destroy; the deploy failure is the one raised
            raise


class Step(Command):
    def execute(self, deployment_id: str, test_type: str, step: int, replace: bool) -> None:
        state = DeploymentState.locate(self.results_root, deployment_id)
        run_log = self._run_log(state.read()["run_id"], "step")
        with DeploymentLock(state, run_log, f"step {test_type} {step}"):
            data = state.read()  # read under the lock, so no other command can change it until the step ends
            self._refuse(deployment_id, data, test_type, step)
            self._run(state, data, run_log, test_type, step, replace)

    @staticmethod
    def _refuse(deployment_id: str, data: dict[str, Any], test_type: str, step: int) -> None:
        if data["teardown_at"]:
            raise StepRefused(f"{deployment_id} was torn down at {data['teardown_at']}")
        if not data["deployment"]:
            raise StepRefused(f"{deployment_id} has no deployment: deploy.sh did not finish")
        if step not in data["load_steps"]:
            raise StepRefused(f"step {step} is not a load step of {deployment_id}; its load steps: {data['load_steps']}")
        if test_type not in TestType:
            raise StepRefused(f"test type '{test_type}' is not one of {', '.join(TestType)}")

    def _run(self, state: DeploymentState, data: dict[str, Any], run_log: RunLog, test_type: str, step: int, replace: bool) -> None:
        run, deployment, host = state.run_info(), self._deployment(data), HostRegistry.get(data["host"])
        layout = ResultsLayout(self.results_root, run.run_id)
        step_dir = layout.step_dir(run.platform, run.host, run.mode, run.message_type, test_type, step, data["load_steps"])
        if step_dir.exists():
            if not replace:
                raise StepRefused(f"{step_dir} already exists; use --replace to run the step again")
            shutil.rmtree(step_dir)
        run_log.info(f"step {test_type} {step} of {run.deployment_id} started")
        runner = StepRunner(self.config, host, FetcherInvoker(run, deployment, run_log), run_log)
        record = asyncio.run(runner.run(run, deployment, data["auth_secret"], test_type, step, step_dir))
        with state.update() as d:
            d["steps"][f"{test_type}/{step}"] = {
                "started": KeyedCsv.cell(record.started),
                "before_end": KeyedCsv.cell(record.before_end),
                "t_load_up": KeyedCsv.cell(record.t_load_up),
                "t_load_down": KeyedCsv.cell(record.t_load_down),
                "ended": KeyedCsv.cell(record.ended),
                "cooldown_max_reached": record.cooldown_max_reached,
            }
        PerRequestWriter(DriverFactory.driver_class(run.mode, run.message_type)).write(step_dir, record.load.records)
        PerWindowWriter(self.config, host, deployment).write(step_dir, record)
        StepMetadataWriter().write(step_dir, self.config, host, run, record)
        run_log.info(f"step {test_type} {step} of {run.deployment_id} done")

    def force_unlock(self, deployment_id: str, yes: bool) -> None:
        state = DeploymentState.locate(self.results_root, deployment_id)
        confirm = (lambda _: True) if yes else self._ask
        DeploymentLock(state, self._run_log(state.read()["run_id"], "step"), "step --force-unlock").force_unlock(confirm)

    @staticmethod
    def _ask(prompt: str) -> bool:
        try:
            return input(prompt).strip().lower() in ("y", "yes")
        except EOFError:  # Ctrl-D or no terminal: not confirmed
            return False


class Plot(Command):
    def execute(self, deployment_id: str | None, run_id: str | None) -> None:
        for state in self._states(deployment_id, run_id):
            with DeploymentLock(state, self._run_log(state.read()["run_id"], "plot"), "plot"):
                self.draw(state)

    def draw(self, state: DeploymentState) -> None:
        """Every step's graphs from its CSVs, and the cost graph when cost.csv exists. The caller holds the lock."""
        data = state.read()
        run_log = self._run_log(data["run_id"], "plot")
        host, deployment, deployment_dir = HostRegistry.get(data["host"]), self._deployment(data), state.path.parent
        for test_type in TestType:
            for step_dir in sorted((deployment_dir / test_type).glob("step-*")):
                if (step_dir / "per-request.csv").exists():  # a step stopped before its CSVs has nothing to draw
                    StepPlots(run_log).draw(step_dir, test_type, host, deployment)
        CostReport(run_log).draw(deployment_dir)


class Finish(Command):
    def execute(self, deployment_id: str) -> bool:
        """Returns whether post-run is needed."""
        state = DeploymentState.locate(self.results_root, deployment_id)
        run_log = self._run_log(state.read()["run_id"], "finish")
        with DeploymentLock(state, run_log, "finish"):
            return self._finish(state, run_log)

    def _finish(self, state: DeploymentState, run_log: RunLog) -> bool:
        data = state.read()
        host = HostRegistry.get(data["host"])
        invoker = FetcherInvoker(state.run_info(), self._deployment(data), run_log)
        start, end = self._time(data["deploy_started"]), self._now()
        stored = [invoker.fetch_and_store(f, "after_all_steps", start, end, state.path.parent) for f in host.fetchers.after_all_steps]
        if any(stored):
            Plot(self.config, self.results_root, self.deploy_root).draw(state)
        self._destroy(state, run_log)
        run_log.info(f"tore down {data['deployment_id']}")
        names = [f.name for f in host.fetchers.after_teardown]
        print(f"post-run needed: {', '.join(names)}" if names else "post-run not needed")
        return bool(names)


class PostRun(Command):
    def execute(self, deployment_id: str | None, run_id: str | None) -> None:
        states = self._states(deployment_id, run_id)
        for state in states:  # checked before the lock: a set teardown_at is never cleared
            if not state.read()["teardown_at"]:
                raise StepRefused(f"{state.read()['deployment_id']} is not torn down; run finish first")
        for state in states:
            run_log = self._run_log(state.read()["run_id"], "post-run")
            with DeploymentLock(state, run_log, "post-run"):
                self._post_run(state, run_log)

    def _post_run(self, state: DeploymentState, run_log: RunLog) -> None:
        data = state.read()
        invoker = FetcherInvoker(state.run_info(), self._deployment(data), run_log)
        start, end = self._time(data["deploy_started"]), self._time(data["teardown_at"])
        for f in HostRegistry.get(data["host"]).fetchers.after_teardown:
            invoker.fetch_and_store(f, "after_teardown", start, end, state.path.parent)
        Plot(self.config, self.results_root, self.deploy_root).draw(state)


class Run(Command):
    def __init__(self, config: BenchConfig, results_root: Path, deploy_root: Path):
        super().__init__(config, results_root, deploy_root)
        self.deploy = Deploy(config, results_root, deploy_root)
        self.step = Step(config, results_root, deploy_root)
        self.plot = Plot(config, results_root, deploy_root)
        self.finish = Finish(config, results_root, deploy_root)

    def execute(self, hosts: list[str] | None, modes: list[str] | None, message_types: list[str] | None, steps: list[int] | None) -> None:
        hosts = hosts or self.config.hosts or HostRegistry.names()
        modes = modes or self.config.modes or list(dict.fromkeys(m for m, _ in DriverFactory.BUILTINS))
        message_types = message_types or self.config.message_types or list(dict.fromkeys(t for _, t in DriverFactory.BUILTINS))
        bad = [s for s in steps or [] if s not in self.config.load_steps]
        if bad:
            raise BenchConfigError(f"--steps {', '.join(map(str, bad))} not in load_steps {self.config.load_steps}")
        combinations = list(dict.fromkeys((h, m, t) for h in hosts for m in modes for t in message_types))
        if not combinations:
            raise BenchConfigError(f"nothing to run: hosts {hosts}, modes {modes}, message types {message_types}")
        for combination in combinations:  # a bad combination is refused before the first deploy
            self.deploy.check(*combination)

        run_id = self._new_run_id()
        run_log = self._run_log(run_id, "run")
        selected = [n for n in self.config.load_steps if not steps or n in steps]
        for combination in combinations:
            deployment_id = self.deploy.execute(*combination, run_id)
            try:
                for n in selected:
                    for test_type in self.config.test_types:
                        self.step.execute(deployment_id, test_type, n, False)
                self.plot.execute(deployment_id, None)
            except Exception:  # Ctrl-C stops the run at once and tears nothing down
                self._finish_after_error(deployment_id, run_log)
                raise
            self.finish.execute(deployment_id)

    def _finish_after_error(self, deployment_id: str, run_log: RunLog) -> None:
        """Tears down after a failed step or plot; the step's or plot's error is the one raised."""
        try:
            self.finish.execute(deployment_id)
        except Exception as e:  # noqa: BLE001 - logged; the earlier error is the one raised
            run_log.error(f"finish of {deployment_id} failed after an earlier error: {type(e).__name__}: {e}")
