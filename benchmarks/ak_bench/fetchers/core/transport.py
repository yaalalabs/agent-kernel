from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from ak_bench.fetchers.core.info_fetcher import InfoFetcher
from ak_bench.results.common.keyed_csv import KeyedCsv


@dataclass
class QueueDepth:
    ts: datetime
    queue: str
    waiting: int
    in_flight: int


@dataclass
class QueueInfo:
    samples: list[QueueDepth] = field(default_factory=list)


class TransportCollector(InfoFetcher[QueueInfo]):
    result_type = QueueInfo

    def store(self, result: QueueInfo, results: Path) -> None:
        KeyedCsv(results / "queue-depth.csv", ["ts", "queue", "waiting", "in_flight", "fetcher"], ["ts", "queue", "fetcher"]).upsert(
            {**asdict(sample), "fetcher": self.name} for sample in result.samples
        )

    def is_settled(self, now: QueueInfo, start: QueueInfo | None) -> bool:
        latest = {s.queue: s for s in sorted(now.samples, key=lambda s: s.ts)}
        return all(s.waiting == 0 and s.in_flight == 0 for s in latest.values())

    def has_value(self, result: QueueInfo) -> bool:
        return bool(result.samples)
