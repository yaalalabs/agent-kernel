from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from agentkernel.core import TraceStage

from ak_bench.fetchers.core.info_fetcher import InfoFetcher
from ak_bench.results.common.keyed_csv import KeyedCsv


@dataclass
class TraceInfo:
    stages: dict[str, dict[TraceStage, datetime]] = field(default_factory=dict)  # {request_id: {stage: ts}}


class TraceCollector(InfoFetcher[TraceInfo]):
    result_type = TraceInfo

    def store(self, result: TraceInfo, results: Path) -> None:
        KeyedCsv(results / "stage-timestamps.csv", ["request_id", "stage", "ts"], ["request_id", "stage"]).upsert(
            {"request_id": request_id, "stage": stage, "ts": ts} for request_id, stages in result.stages.items() for stage, ts in stages.items()
        )
