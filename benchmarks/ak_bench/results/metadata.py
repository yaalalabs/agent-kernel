import json
import subprocess
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from ak_bench.config import BenchConfig, TestType
from ak_bench.hosts.host import Deployment, Host, RunInfo
from ak_bench.results.common.keyed_csv import KeyedCsv
from ak_bench.results.common.percentiles import METHOD
from ak_bench.run.step_runner import StepRecord


class JsonFile:
    @staticmethod
    def write(path: Path, data: dict[str, Any]) -> None:
        """Datetimes in the CSV format; temp file then rename, so a stopped run leaves no half file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=KeyedCsv.cell) + "\n")
        tmp.replace(path)


class RunMetadataWriter:
    """run-metadata.json, written by `deploy`. Recorded only, never compared."""

    # #786 Run metadata fields the host gives through deployment.json `settings`; one it doesn't give is written as null
    HOST_FIELDS = ("region", "tiers", "transport", "session_store", "resource_usage", "front_door")

    def write(self, deployment_dir: Path, run: RunInfo, started: datetime, deployment: Deployment, mock_delays: tuple[float, float] | None) -> None:
        data = {
            "run_id": run.run_id,
            "deployment_id": run.deployment_id,
            "started": started,
            "host": run.host,
            "platform": run.platform,
            "mode": run.mode,
            "message_type": run.message_type,
            "ak_version": version("agentkernel"),
            "git_commit": self._git_commit(),
            "agent": "real" if mock_delays is None else "mock",
            "mock_agent_min_delay_s": mock_delays and mock_delays[0],
            "mock_agent_max_delay_s": mock_delays and mock_delays[1],
        }
        # A host setting never replaces a field the harness records itself
        host_values = {**dict.fromkeys(self.HOST_FIELDS), **deployment.settings}
        JsonFile.write(deployment_dir / "run-metadata.json", data | {k: v for k, v in host_values.items() if k not in data})

    @staticmethod
    def _git_commit() -> str:
        try:
            out = subprocess.run(["git", "rev-parse", "HEAD"], check=False, cwd=Path(__file__).parent, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return ""
        return out.stdout.strip() if out.returncode == 0 else ""


class StepMetadataWriter:
    """step-metadata.json, written by `step`: the benchmark settings the step ran with (ak-bench.yaml can change between steps)."""

    def write(self, step_dir: Path, config: BenchConfig, host: Host, run: RunInfo, record: StepRecord) -> None:
        cfg, traffic = config.step_run, config.steady_traffic
        steady = record.test_type == TestType.STEADY  # the steady-traffic settings don't apply to burst: null, like seed
        JsonFile.write(
            step_dir / "step-metadata.json",
            {
                "test_type": record.test_type,
                "step": record.step,
                "min_send_interval_s": traffic.min_send_interval_s if steady else None,
                "max_send_interval_s": traffic.max_send_interval_s if steady else None,
                "load_time_s": traffic.load_time_s if steady else None,
                "before_window_s": cfg.before_window_s,
                "max_cooldown_s": config.max_cooldown_for(run.host),
                "after_step_wait_s": cfg.after_step_wait_s,
                "cooldown_poll_interval_s": cfg.cooldown_poll_interval_s,
                "cooldown_lookback_s": cfg.cooldown_lookback_s,
                "poll_intervals_s": {f.name: f.poll_interval_s or config.fetchers.poll_interval_for(f.name) for f in host.fetchers.all()},
                "client_timeout_s": cfg.client_timeout_s,
                "time_window_s": cfg.time_window_s,
                "percentile_method": METHOD,
                "seed": record.seed,
                "started": record.started,
                "before_end": record.before_end,
                "t_load_up": record.t_load_up,
                "t_load_down": record.t_load_down,
                "ended": record.ended,
            },
        )
