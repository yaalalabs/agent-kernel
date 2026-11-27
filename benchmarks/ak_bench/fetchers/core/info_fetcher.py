from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from ak_bench.errors import FetcherTypeError
from ak_bench.hosts.host import Deployment, RunInfo


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
