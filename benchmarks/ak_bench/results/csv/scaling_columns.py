from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from ak_bench.fetchers.core.scaling import ScalingInfoFetcher
from ak_bench.hosts.host import Deployment, Host
from ak_bench.results.common.keyed_csv import KeyedCsv

if TYPE_CHECKING:
    from ak_bench.results.csv.per_window import WindowGrid


class ScalingCollector:
    """The per-window `<tier>.<count_type>.<fetcher>` columns from scaling-samples.csv."""

    def __init__(self, host: Host, deployment: Deployment, polled: dict[str, float]):
        self.host = host
        self.deployment = deployment
        self.polled = polled

    def columns(self, step_dir: Path, grid: WindowGrid) -> dict[str, list[Any]]:
        # Laid out from the host and deployment first, so a fetcher that stored nothing still has its empty columns
        columns: dict[str, list[Any]] = {
            f"{tier}.{count_type}.{f.name}": [None] * len(grid.windows)
            for f in self.host.fetchers.in_step_lists(ScalingInfoFetcher)
            for tier in self.deployment.resources
            for count_type in sorted(f.count_types)
        }
        series = KeyedCsv(step_dir / "scaling-samples.csv", [], []).series(
            lambda r: (r["tier"], r["count_type"], r["fetcher"]), lambda r: int(r["value"])
        )
        for (tier, count_type, fetcher), samples in series.items():
            columns[f"{tier}.{count_type}.{fetcher}"] = grid.fill(samples, self.polled.get(fetcher))
        return columns
