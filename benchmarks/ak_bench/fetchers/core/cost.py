from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from ak_bench.fetchers.core.info_fetcher import InfoFetcher
from ak_bench.results.common.keyed_csv import KeyedCsv


@dataclass
class CostItem:
    period_start: datetime
    period_end: datetime
    service: str
    usd: float
    metric: str


@dataclass
class CostInfo:
    items: list[CostItem] = field(default_factory=list)


class CostFetcher(InfoFetcher[CostInfo]):
    result_type = CostInfo

    def store(self, result: CostInfo, results: Path) -> None:
        KeyedCsv(
            results / "cost.csv",
            ["period_start", "period_end", "service", "usd", "metric", "fetcher"],
            ["period_start", "period_end", "service", "metric", "fetcher"],
        ).upsert({**asdict(item), "fetcher": self.name} for item in result.items)
