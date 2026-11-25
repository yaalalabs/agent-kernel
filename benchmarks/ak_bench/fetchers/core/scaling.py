from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from ak_bench.fetchers.core.info_fetcher import InfoFetcher
from ak_bench.results.common.keyed_csv import KeyedCsv


@dataclass
class CountSample:
    ts: datetime
    tier: str
    count_type: str
    value: int


@dataclass
class WorkerSpan:
    tier: str
    worker: str
    started: datetime
    stopped: datetime | None
    extra: dict = field(default_factory=dict)


@dataclass
class ScalingInfo:
    samples: list[CountSample] = field(default_factory=list)
    spans: list[WorkerSpan] = field(default_factory=list)


class ScalingInfoFetcher(InfoFetcher[ScalingInfo]):
    result_type = ScalingInfo
    count_types: frozenset[str] = frozenset()

    def store(self, result: ScalingInfo, results: Path) -> None:
        KeyedCsv(results / "scaling-samples.csv", ["ts", "tier", "count_type", "value", "fetcher"], ["ts", "tier", "count_type", "fetcher"]).upsert(
            {**asdict(sample), "fetcher": self.name} for sample in result.samples
        )
        KeyedCsv(results / "worker-spans.csv", ["tier", "worker", "started", "stopped", "extra", "fetcher"], ["tier", "worker", "fetcher"]).upsert(
            {**asdict(span), "fetcher": self.name} for span in result.spans
        )

    def is_settled(self, now: ScalingInfo, start: ScalingInfo | None) -> bool:
        if start is None:
            return False
        now_running = self._latest_running(now)
        return all(now_running.get(tier) == value for tier, value in self._latest_running(start).items())

    def has_value(self, result: ScalingInfo) -> bool:
        return any(sample.count_type == "running" for sample in result.samples)

    @staticmethod
    def _latest_running(info: ScalingInfo) -> dict[str, int]:
        """{tier: value of its latest `running` sample}."""
        return {s.tier: s.value for s in sorted(info.samples, key=lambda s: s.ts) if s.count_type == "running"}
