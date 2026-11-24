from pathlib import Path
from statistics import fmean
from typing import Any

from ak_bench.load.records import RequestStatus
from ak_bench.results.keyed_csv import KeyedCsv
from ak_bench.results.per_request import DURATION_STAGES
from ak_bench.results.percentiles import percentiles
from ak_bench.run.step_runner import StepRecord


class SummaryWriter:
    """summary.csv per test type: one row per step, keyed by `step`, so a re-run step replaces its own row."""

    @staticmethod
    def build(
        record: StepRecord, requests: list[dict[str, Any]], windows: list[dict[str, Any]], scaling: dict[str, Any], resources: dict[str, Any]
    ) -> dict[str, Any]:
        """The step's row, from its records, its per-request and per-window rows, and the scaling and resource numbers."""
        records = record.load.records
        latencies = [r.latency_s for r in records if r.latency_s is not None]
        row: dict[str, Any] = {
            "step": record.step,
            "started": record.started,
            "ended": record.ended,
            "cooldown_max_reached": record.cooldown_max_reached,
            "requests": len(records),
            **{
                column: sum(r.status == status for r in records)
                for column, status in (("ok", RequestStatus.OK), ("errors", RequestStatus.ERROR), ("timeouts", RequestStatus.TIMEOUT))
            },
            "time_to_answer_all_s": record.load.time_to_answer_all_s,
            **{f"latency_{p}": v for p, v in percentiles(latencies).items()},
            "latency_n": len(latencies),
        }
        for stage in DURATION_STAGES:
            durations = [r[f"{stage}_s"] for r in requests if r[f"{stage}_s"] is not None]
            row |= {f"{stage}_{p}": v for p, v in percentiles(durations).items()}
            row[f"{stage}_n"] = len(durations)
        loaded = [w for w in windows if w["step_part"] != "before"]
        for direction in ("tx", "rx"):
            rates = [w[f"{direction}_per_s"] for w in loaded]
            row |= {
                f"{direction}_min": min(rates, default=None),
                f"{direction}_avg": fmean(rates) if rates else None,
                f"{direction}_max": max(rates, default=None),
            }
        return row | scaling | resources

    def upsert(self, test_type_dir: Path, row: dict[str, Any]) -> None:
        path = test_type_dir / "summary.csv"
        # Steps can bring new series (e.g. a tier seen only at a larger step), so the header grows, never shrinks
        columns = list(dict.fromkeys([*KeyedCsv(path, [], []).header(), *row]))
        KeyedCsv(path, columns, ["step"]).upsert([row])

    def remove(self, test_type_dir: Path, step: int) -> None:
        """Drops the step's row, for `step --replace`."""
        path = test_type_dir / "summary.csv"
        KeyedCsv(path, KeyedCsv(path, [], []).header(), ["step"]).remove([(str(step),)])
