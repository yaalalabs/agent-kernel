from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from ak_bench.fetchers.core.info_fetcher import InfoFetcher
from ak_bench.results.common.keyed_csv import KeyedCsv


@dataclass
class ResourceSample:
    ts: datetime
    tier: str
    worker: str | None
    metric: str
    stat: str
    value: float


@dataclass
class ResourceUsage:
    samples: list[ResourceSample] = field(default_factory=list)


class ResourceUsageFetcher(InfoFetcher[ResourceUsage]):
    result_type = ResourceUsage
    metrics: frozenset[tuple[str, str]] = frozenset()  # (metric, stat) pairs; lays out empty columns when nothing was stored

    def store(self, result: ResourceUsage, results: Path) -> None:
        KeyedCsv(
            results / "resource-usage.csv",
            ["ts", "tier", "worker", "metric", "stat", "value", "fetcher"],
            ["ts", "tier", "worker", "metric", "stat", "fetcher"],
        ).upsert({**asdict(sample), "fetcher": self.name} for sample in result.samples)
