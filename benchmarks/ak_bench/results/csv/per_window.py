from collections.abc import Iterable
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

from ak_bench.config import BenchConfig
from ak_bench.fetchers.core.transport import TransportCollector
from ak_bench.hosts.host import Deployment, Host
from ak_bench.load.records import RequestStatus
from ak_bench.results.common.keyed_csv import KeyedCsv
from ak_bench.results.common.percentiles import percentiles
from ak_bench.results.csv.resource_columns import ResourceCollector
from ak_bench.results.csv.scaling_columns import ScalingCollector
from ak_bench.run.step_runner import StepRecord


class WindowGrid:
    """Windows of time_window_s from the step start: window k is [started + k·w, started + (k+1)·w); the last ends at or after `ended`."""

    def __init__(self, started: datetime, ended: datetime, time_window_s: float):
        self.started = started
        self.w = time_window_s
        # timedelta arithmetic is exact in microseconds; float seconds would put a boundary sample in the window before it
        self.step = timedelta(seconds=time_window_s)
        n = max(1, -(-(ended - started) // self.step))
        self.windows = [(started + k * self.step, started + (k + 1) * self.step) for k in range(n)]

    def index(self, ts: datetime | None) -> int | None:
        """The window ts falls in, None outside the grid."""
        if ts is None:
            return None
        k = (ts - self.started) // self.step
        return k if 0 <= k < len(self.windows) else None

    def bucket(self, items: Iterable[tuple[datetime | None, Any]]) -> list[list[Any]]:
        """Items grouped by the window their time falls in."""
        out: list[list[Any]] = [[] for _ in self.windows]
        for ts, item in items:
            if (k := self.index(ts)) is not None:
                out[k].append(item)
        return out

    def fill(self, samples: list[tuple[datetime, Any]], poll_interval_s: float | None) -> list[Any]:
        """Per window, the last sample at or before its end, if no older than the carry limit; else None.

        Carry limit: the poll interval for a polled (during_step) series, else the series' smallest positive sample gap; a
        series of one sample fills only the window it falls in.
        """
        samples = sorted(samples, key=lambda s: s[0])
        carry = poll_interval_s if poll_interval_s is not None else self.sample_period([ts for ts, _ in samples])
        out, last, i = [], None, 0
        for start, end in self.windows:
            while i < len(samples) and samples[i][0] <= end:
                last, i = samples[i], i + 1
            if last is None:
                out.append(None)
            elif carry is None:
                out.append(last[1] if start <= last[0] < end else None)
            else:
                out.append(last[1] if (end - last[0]).total_seconds() <= carry else None)
        return out

    @staticmethod
    def sample_period(times: list[datetime]) -> float | None:
        return min((g for a, b in pairwise(sorted(times)) if (g := (b - a).total_seconds()) > 0), default=None)


class PerWindowWriter:
    """Writes per-time-window.csv from the step's records and its raw fetcher files."""

    def __init__(self, config: BenchConfig, host: Host, deployment: Deployment):
        self.config = config
        self.host = host
        self.deployment = deployment
        # Carry limit of a polled series: the fetcher's resolved poll interval
        self.polled = {f.name: f.poll_interval_s or config.fetchers.poll_interval_for(f.name) for f in host.fetchers.during_step}

    def write(self, step_dir: Path, record: StepRecord) -> list[dict[str, Any]]:
        """Writes the file and returns its rows (values, not CSV cells)."""
        grid = WindowGrid(record.started, record.ended, self.config.step_run.time_window_s)
        columns = self._client_columns(grid, record)
        columns |= self._queue_columns(step_dir, grid)
        columns |= ScalingCollector(self.host, self.deployment, self.polled).columns(step_dir, grid)
        columns |= ResourceCollector(self.host, self.deployment, self.polled).columns(step_dir, grid)
        rows = [{c: values[k] for c, values in columns.items()} for k in range(len(grid.windows))]
        KeyedCsv(step_dir / "per-time-window.csv", list(columns), ["window_start"]).upsert(rows)
        return rows

    def _client_columns(self, grid: WindowGrid, record: StepRecord) -> dict[str, list[Any]]:
        records, w = record.load.records, grid.w
        sent = grid.bucket((r.sent, r) for r in records)
        ok = grid.bucket((r.complete, r.latency_s) for r in records if r.status == RequestStatus.OK)
        errors = grid.bucket((r.settled, r) for r in records if r.status == RequestStatus.ERROR)
        timeouts = grid.bucket((r.settled, r) for r in records if r.status == RequestStatus.TIMEOUT)
        latency = [percentiles(latencies) for latencies in ok]
        return {
            "window_start": [start for start, _ in grid.windows],
            "step_part": [self._part(start, end, record) for start, end in grid.windows],
            "tx_per_s": [len(b) / w for b in sent],
            "rx_per_s": [len(b) / w for b in ok],
            "errors": [len(b) for b in errors],
            "timeouts": [len(b) for b in timeouts],
            **{f"latency_{p}": [pct[p] for pct in latency] for p in latency[0]},
        }

    def _queue_columns(self, step_dir: Path, grid: WindowGrid) -> dict[str, list[Any]]:
        fetchers = [f.name for f in self.host.fetchers.in_step_lists(TransportCollector)]
        columns: dict[str, list[Any]] = {}
        for queue in self.deployment.queues:
            for fetcher in fetchers:
                columns[f"{queue}.waiting.{fetcher}"] = columns[f"{queue}.in_flight.{fetcher}"] = [None] * len(grid.windows)
        series = KeyedCsv(step_dir / "queue-depth.csv", [], []).series(
            lambda r: (r["queue"], r["fetcher"]), lambda r: (int(r["waiting"]), int(r["in_flight"]))
        )
        for (queue, fetcher), samples in series.items():
            filled = grid.fill(samples, self.polled.get(fetcher))
            columns[f"{queue}.waiting.{fetcher}"] = [v and v[0] for v in filled]
            columns[f"{queue}.in_flight.{fetcher}"] = [v and v[1] for v in filled]
        return columns

    @staticmethod
    def _part(start: datetime, end: datetime, record: StepRecord) -> str:
        """The part covering most of the window within the step; the boundaries are not on the grid (ms after it)."""
        parts = {
            "before": (record.started, record.before_end),
            "load": (record.before_end, record.t_load_down),
            "cooldown": (record.t_load_down, record.ended),
        }
        overlap = {part: min(end, b) - max(start, a) for part, (a, b) in parts.items()}
        return max(overlap, key=overlap.__getitem__)
