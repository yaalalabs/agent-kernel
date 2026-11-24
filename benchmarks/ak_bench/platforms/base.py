from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from agentkernel.core import TraceStage

from ak_bench.errors import FetcherTypeError, HostRefused, ScriptFailed
from ak_bench.results.keyed_csv import KeyedCsv


@dataclass(frozen=True)
class RunInfo:
    """The `run` argument of fetch(): who is running, never results."""

    run_id: str
    deployment_id: str  # "<run-id>-<host>-<mode>-<message-type>", also the cloud tag value
    host: str
    platform: str
    mode: str
    message_type: str


@dataclass
class Deployment:
    """Read from deployment.json, saved in state.json unchanged."""

    endpoint: str
    resources: dict[str, dict[str, Any]]
    queues: dict[str, dict[str, Any]]
    logs: dict[str, str]
    settings: dict[str, Any]

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Deployment":
        if not isinstance(data, dict):
            raise ScriptFailed(f"deployment.json must be a JSON object, got {type(data).__name__}")
        missing = [key for key in ("endpoint", "resources", "queues", "logs", "settings") if key not in data]
        if missing:
            raise ScriptFailed(f"deployment.json is missing {', '.join(missing)}")
        return cls(data["endpoint"], data["resources"], data["queues"], data["logs"], data["settings"])

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


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


@dataclass
class TraceInfo:
    stages: dict[str, dict[TraceStage, datetime]] = field(default_factory=dict)  # {request_id: {stage: ts}}


@dataclass
class QueueDepth:
    ts: datetime
    queue: str
    waiting: int
    in_flight: int


@dataclass
class QueueInfo:
    samples: list[QueueDepth] = field(default_factory=list)


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


class InfoFetcher[T](ABC):
    """Reads one kind of information about a deployment and stores it under the results folder."""

    name: str
    result_type: ClassVar[type]

    def __init__(self, poll_interval_s: float | None = None, settle_window_s: float = 0):
        self.poll_interval_s = poll_interval_s
        self.settle_window_s = settle_window_s

    @abstractmethod
    def fetch(self, run: RunInfo, deployment: Deployment, start: datetime, end: datetime) -> T: ...

    @abstractmethod
    def store(self, result: T, results: Path) -> None: ...

    def is_settled(self, now: T, start: T | None) -> bool:
        raise NotImplementedError

    def has_value(self, result: T) -> bool:
        return True

    def fetch_and_store(self, run: RunInfo, deployment: Deployment, start: datetime, end: datetime, results: Path) -> None:
        result = self.fetch(run, deployment, start, end)
        if not isinstance(result, self.result_type):
            raise FetcherTypeError(f"fetcher '{self.name}': fetch() returned {type(result).__name__}, expected {self.result_type.__name__}")
        self.store(result, results)


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


class ResourceUsageFetcher(InfoFetcher[ResourceUsage]):
    result_type = ResourceUsage
    metrics: frozenset[tuple[str, str]] = frozenset()  # (metric, stat) pairs; lays out empty columns when nothing was stored

    def store(self, result: ResourceUsage, results: Path) -> None:
        KeyedCsv(
            results / "resource-usage.csv",
            ["ts", "tier", "worker", "metric", "stat", "value", "fetcher"],
            ["ts", "tier", "worker", "metric", "stat", "fetcher"],
        ).upsert({**asdict(sample), "fetcher": self.name} for sample in result.samples)


class TraceCollector(InfoFetcher[TraceInfo]):
    result_type = TraceInfo

    def store(self, result: TraceInfo, results: Path) -> None:
        KeyedCsv(results / "stage-timestamps.csv", ["request_id", "stage", "ts"], ["request_id", "stage"]).upsert(
            {"request_id": request_id, "stage": stage, "ts": ts} for request_id, stages in result.stages.items() for stage, ts in stages.items()
        )


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


class CostFetcher(InfoFetcher[CostInfo]):
    result_type = CostInfo

    def store(self, result: CostInfo, results: Path) -> None:
        KeyedCsv(
            results / "cost.csv",
            ["period_start", "period_end", "service", "usd", "metric", "fetcher"],
            ["period_start", "period_end", "service", "metric", "fetcher"],
        ).upsert({**asdict(item), "fetcher": self.name} for item in result.items)


@dataclass
class Fetchers:
    during_step: list[InfoFetcher] = field(default_factory=list)
    cooldown_checks: list[InfoFetcher] = field(default_factory=list)
    after_step: list[InfoFetcher] = field(default_factory=list)
    after_all_steps: list[InfoFetcher] = field(default_factory=list)
    after_teardown: list[InfoFetcher] = field(default_factory=list)

    def all(self) -> list[InfoFetcher]:
        """Every distinct fetcher object, first-seen order."""
        lists = (self.during_step, self.cooldown_checks, self.after_step, self.after_all_steps, self.after_teardown)
        return list({id(f): f for fetchers in lists for f in fetchers}.values())

    def in_step_lists(self, family: type) -> list[InfoFetcher]:
        """Distinct fetchers of this family in during_step, cooldown_checks or after_step, first-seen order."""
        lists = (self.during_step, self.cooldown_checks, self.after_step)
        return list({id(f): f for fetchers in lists for f in fetchers if isinstance(f, family)}.values())

    def validate(self, host: str) -> None:
        for f in self.all():
            if not getattr(f, "name", ""):
                raise HostRefused(f"host '{host}': fetcher {type(f).__name__} has no name")
        for f in self.cooldown_checks:
            if type(f).is_settled is InfoFetcher.is_settled:
                raise HostRefused(f"host '{host}': cooldown_checks fetcher '{f.name}' does not implement is_settled()")
            if isinstance(f, ScalingInfoFetcher) and "running" not in f.count_types:
                raise HostRefused(f"host '{host}': cooldown_checks fetcher '{f.name}' does not give the 'running' count type")


@dataclass(frozen=True)
class Host:
    platform: str
    fetchers: Fetchers
