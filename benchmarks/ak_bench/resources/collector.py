from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import fmean
from typing import TYPE_CHECKING, Any

from ak_bench.platforms.base import Deployment, Host, ResourceUsageFetcher
from ak_bench.results.keyed_csv import KeyedCsv
from ak_bench.results.percentiles import percentiles

if TYPE_CHECKING:
    from ak_bench.results.per_window import WindowGrid


class ResourceCollector:
    """CPU / memory columns from resource-usage.csv, per tier × metric × stat × fetcher.

    A `value` series (one value per worker) gives p0..p100 over the workers; a `min` / `avg` / `max` series gives one
    column, combined as min of min, mean of avg, max of max.
    """

    def __init__(self, host: Host, deployment: Deployment, polled: dict[str, float]):
        self.host = host
        self.deployment = deployment
        self.polled = polled

    def columns(self, step_dir: Path, grid: WindowGrid) -> dict[str, list[Any]]:
        """Per window, each worker's carried value, combined across the workers."""
        n = len(grid.windows)
        columns = {c: [None] * n for c in self._declared()}
        for (tier, metric, stat, fetcher), workers in self._series(step_dir).items():
            per_worker = [grid.fill(samples, self.polled.get(fetcher)) for samples in workers.values()]
            per_window = [[v[k] for v in per_worker if v[k] is not None] for k in range(n)]
            for k, values in enumerate(per_window):
                for column, value in self._combine(tier, metric, stat, fetcher, values).items():
                    columns.setdefault(column, [None] * n)[k] = value
        return columns

    def summary(self, step_dir: Path, started: datetime, ended: datetime) -> dict[str, Any]:
        """The summary.csv columns: the same combination over every raw sample in [started, ended]."""
        out: dict[str, Any] = dict.fromkeys(self._declared())
        for (tier, metric, stat, fetcher), workers in self._series(step_dir).items():
            values = [v for samples in workers.values() for ts, v in samples if started <= ts <= ended]
            out |= self._combine(tier, metric, stat, fetcher, values)
        return out

    def _declared(self) -> list[str]:
        """Columns laid out from the host and deployment, so a fetcher that stored nothing still has its empty columns."""
        return [
            column
            for f in self.host.fetchers.in_step_lists(ResourceUsageFetcher)
            for tier in self.deployment.resources
            for metric, stat in sorted(f.metrics)
            for column in self._combine(tier, metric, stat, f.name, [])
        ]

    @staticmethod
    def _series(step_dir: Path) -> dict[tuple, dict[str, list[tuple[datetime, float]]]]:
        """{(tier, metric, stat, fetcher): {worker: [(ts, value)]}}."""
        rows = KeyedCsv(step_dir / "resource-usage.csv", [], []).series(
            lambda r: (r["tier"], r["metric"], r["stat"], r["fetcher"], r["worker"]), lambda r: float(r["value"])
        )
        out: dict[tuple, dict[str, list[tuple[datetime, float]]]] = defaultdict(dict)
        for (*series, worker), samples in rows.items():
            out[tuple(series)][worker] = samples
        return out

    @staticmethod
    def _combine(tier: str, metric: str, stat: str, fetcher: str, values: list[float]) -> dict[str, float | None]:
        if stat == "value":
            return {f"{tier}.{metric}.{p}.{fetcher}": v for p, v in percentiles(values).items()}
        # shortcut: a stat other than min / max is averaged; add its rule here if a fetcher gives one (e.g. sum)
        combine = {"min": min, "max": max}.get(stat, fmean)
        return {f"{tier}.{metric}.{stat}.{fetcher}": combine(values) if values else None}
