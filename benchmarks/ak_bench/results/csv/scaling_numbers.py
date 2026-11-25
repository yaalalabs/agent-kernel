from collections import defaultdict
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

from ak_bench.fetchers.core.scaling import ScalingInfoFetcher
from ak_bench.fetchers.core.transport import TransportCollector
from ak_bench.hosts.host import Deployment, Host
from ak_bench.results.common.keyed_csv import KeyedCsv
from ak_bench.run.step_runner import StepRecord

Series = list[tuple[datetime, int]]  # (ts, value), sorted by ts


class ScalingDerivation:
    """The summary's scaling numbers, from raw sample times (not windows).

    Definitions: docs/specs/786-benchmark-system/research/platform-scaling-and-cost.md (Derived numbers).
    """

    def __init__(self, host: Host, deployment: Deployment):
        self.host = host
        self.deployment = deployment

    def derive(self, step_dir: Path, record: StepRecord) -> dict[str, Any]:
        """`<tier>.<column>.<fetcher>` per tier × scaling fetcher, `<queue>.backlog_drained_s.<fetcher>` per queue × transport fetcher."""
        # Laid out from the host and deployment first, so a fetcher that stored nothing still has its empty columns
        tiers = [(tier, f.name) for f in self.host.fetchers.in_step_lists(ScalingInfoFetcher) for tier in self.deployment.resources]
        queues = [(queue, f.name) for f in self.host.fetchers.in_step_lists(TransportCollector) for queue in self.deployment.queues]
        counts = KeyedCsv(step_dir / "scaling-samples.csv", [], []).series(
            lambda r: (r["tier"], r["fetcher"], r["count_type"]), lambda r: int(r["value"])
        )
        span_starts: dict[tuple, list[datetime]] = defaultdict(list)
        for row in KeyedCsv(step_dir / "worker-spans.csv", [], []).read():
            span_starts[(row["tier"], row["fetcher"])].append(KeyedCsv.parse_ts(row["started"]))
        waiting = KeyedCsv(step_dir / "queue-depth.csv", [], []).series(lambda r: (r["queue"], r["fetcher"]), lambda r: int(r["waiting"]))

        out: dict[str, Any] = {}
        for tier, fetcher in dict.fromkeys([*tiers, *(k[:2] for k in counts), *span_starts]):
            numbers = self.tier(
                sorted(counts.get((tier, fetcher, "running"), [])),
                sorted(counts.get((tier, fetcher, "desired"), [])),
                span_starts.get((tier, fetcher), []),
                record.started,
                record.t_load_up,
                record.t_load_down,
                record.ended,
            )
            out |= {f"{tier}.{column}.{fetcher}": value for column, value in numbers.items()}
        for queue, fetcher in dict.fromkeys([*queues, *waiting]):
            out[f"{queue}.backlog_drained_s.{fetcher}"] = self.backlog_drained(sorted(waiting.get((queue, fetcher), [])), record.t_load_up)
        return out

    @classmethod
    def tier(
        cls,
        running: Series,
        desired: Series,
        span_starts: list[datetime],
        started: datetime,
        t_load_up: datetime,
        t_load_down: datetime,
        ended: datetime,
    ) -> dict[str, Any]:
        """One tier × fetcher. No `running` source → every running-based column empty; no scaling → counts only."""
        before_up, before_down, after_down = (cls._latest(running, t) for t in (t_load_up, t_load_down, ended))
        peak = max((v for ts, v in running if started <= ts <= ended), default=None)

        desired_before_up = cls._latest(desired, t_load_up)
        decision = next((ts for ts, v in desired if ts > t_load_up and desired_before_up is not None and v > desired_before_up), None)
        increase = next((b_ts for (_, a), (b_ts, b) in pairwise(running) if b_ts > t_load_up and b > a), None)
        new_span = min((ts for ts in span_starts if ts > t_load_up), default=None)
        first_new = min((ts for ts in (increase, new_span) if ts is not None), default=None)

        scaled_up = before_up is not None and peak is not None and peak > before_up
        up_done = next((ts for ts, v in running if ts >= t_load_up and v == peak), None) if scaled_up else None
        down_start = next((b_ts for (_, a), (b_ts, b) in pairwise(desired or running) if b_ts > t_load_down and b < a), None)
        scaled_down = before_up is not None and before_down is not None and before_down > before_up
        down_done = next((ts for ts, v in running if ts > t_load_down and v <= before_up), None) if scaled_down else None

        up_s, down_s = cls._since(up_done, t_load_up), cls._since(down_done, t_load_down)
        return {
            "decision_delay_s": cls._since(decision, t_load_up),
            "first_new_worker_s": cls._since(first_new, t_load_up),
            "scale_up_done_s": up_s,
            "scale_down_start_s": cls._since(down_start, t_load_down),
            "scale_down_done_s": down_s,
            "workers_before_up": before_up,
            "workers_peak": peak,
            "workers_before_down": before_down,
            "workers_after_down": after_down,
            # Never divides by 0: a done time of 0 or none leaves the rate empty
            "scale_up_rate_per_min": (peak - before_up) / (up_s / 60) if up_s else None,
            "scale_down_rate_per_min": (before_down - after_down) / (down_s / 60) if down_s and before_down > after_down else None,
        }

    @classmethod
    def backlog_drained(cls, waiting: Series, t_load_up: datetime) -> float | None:
        """t_load_up → `waiting` back to its level at t_load_up, counting only samples after the first one above it."""
        baseline = cls._latest(waiting, t_load_up)
        if baseline is None:
            return None
        after = [(ts, v) for ts, v in waiting if ts > t_load_up]
        rose = next((i for i, (_, v) in enumerate(after) if v > baseline), None)
        if rose is None:
            return None
        return next((cls._since(ts, t_load_up) for ts, v in after[rose + 1 :] if v <= baseline), None)

    @staticmethod
    def _latest(series: Series, at: datetime) -> int | None:
        return next((v for ts, v in reversed(series) if ts <= at), None)

    @staticmethod
    def _since(ts: datetime | None, ref: datetime) -> float | None:
        return None if ts is None else (ts - ref).total_seconds()
