from datetime import datetime
from typing import Any

from ak_bench.fetchers.core.cost import CostFetcher
from ak_bench.fetchers.core.resources import ResourceUsageFetcher
from ak_bench.fetchers.core.scaling import ScalingInfo, ScalingInfoFetcher
from ak_bench.fetchers.core.trace import TraceCollector
from ak_bench.fetchers.core.transport import TransportCollector
from ak_bench.hosts.host import Deployment, RunInfo


class Scripted:
    """Returns the scripted results (or raises the scripted exceptions) in order, then empty results; logs each (start, end)."""

    def __init__(self, name: str, results: list[Any] = (), **kwargs: Any):
        super().__init__(**kwargs)
        self.name = name
        self.script = list(results)
        self.calls: list[tuple[datetime, datetime]] = []

    def fetch(self, run: RunInfo, deployment: Deployment, start: datetime, end: datetime) -> Any:
        self.calls.append((start, end))
        result = self.script.pop(0) if self.script else self.result_type()
        if isinstance(result, BaseException):
            raise result
        return result


class MockScalingFetcher(Scripted, ScalingInfoFetcher):
    count_types = frozenset({"running", "desired"})


class MockResourceFetcher(Scripted, ResourceUsageFetcher):
    metrics = frozenset({("cpu_pct", "max"), ("mem_pct", "max")})


class MockTraceCollector(Scripted, TraceCollector):
    pass


class MockTransportCollector(Scripted, TransportCollector):
    pass


class MockCostFetcher(Scripted, CostFetcher):
    pass


class RaisingFetcher(Scripted, ResourceUsageFetcher):
    def fetch(self, run: RunInfo, deployment: Deployment, start: datetime, end: datetime) -> Any:
        self.calls.append((start, end))
        raise RuntimeError(f"{self.name} is broken")


class WrongTypeFetcher(Scripted, ResourceUsageFetcher):
    def fetch(self, run: RunInfo, deployment: Deployment, start: datetime, end: datetime) -> Any:
        self.calls.append((start, end))
        return ScalingInfo()
