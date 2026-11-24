from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ak_bench.platforms.base import InfoFetcher
from ak_bench.run.fetcher_invoker import FetcherInvoker


@dataclass(frozen=True)
class StepEnd:
    at: datetime
    max_reached: bool


class StepEndCheck:
    """Decides when a step's cool-down ends: every request settled, then each cooldown_checks fetcher settled for its settle window."""

    LIST_NAME = "cooldown_checks"

    def __init__(self, checks: list[InfoFetcher], invoker: FetcherInvoker, all_settled: Callable[[], bool], lookback_s: float, max_cooldown_s: float):
        self.checks = checks
        self.invoker = invoker
        self.all_settled = all_settled
        self.lookback = timedelta(seconds=lookback_s)
        self.max_cooldown = timedelta(seconds=max_cooldown_s)
        self._start: dict[InfoFetcher, Any] = {}
        self._since: dict[InfoFetcher, datetime | None] = {f: None for f in checks}

    def start(self, now: datetime) -> None:
        """Reads each check's starting value; a failed or empty read leaves it None (not met until the maximum cool-down)."""
        for f in self.checks:
            ok, result = self.invoker.fetch(f, self.LIST_NAME, now - self.lookback, now)
            if ok and not f.has_value(result):
                self.invoker.run_log.warning(f"{f.name}: no starting value")
            self._start[f] = result if ok and f.has_value(result) else None

    def poll(self, now: datetime, t_load_down: datetime) -> StepEnd | None:
        # Checked first, so the maximum ends the step even while a check keeps failing.
        if now - t_load_down >= self.max_cooldown:
            return StepEnd(now, max_reached=True)
        if not self.all_settled():
            self._reset(self.checks)
            return None
        for i, f in enumerate(self.checks):
            if not self._holds(f, now):
                # Later checks are not read this poll, so their settle runs break too (a run means "held in every poll").
                self._reset(self.checks[i + 1 :])
                return None
        return StepEnd(now, max_reached=False)

    def _holds(self, f: InfoFetcher, now: datetime) -> bool:
        """This poll's read is settled and has been in every poll of the last settle_window_s."""
        if self._start.get(f) is None:
            return False  # no starting value: not met until the maximum cool-down, whatever is_settled() would say
        ok, result = self.invoker.fetch(f, self.LIST_NAME, now - self.lookback, now)
        if ok and not f.has_value(result):
            self.invoker.run_log.warning(f"{f.name}: no value in cool-down read")
        if not ok or not f.has_value(result) or not f.is_settled(result, self._start.get(f)):
            self._since[f] = None
            return False
        self._since[f] = self._since[f] or now
        return (now - self._since[f]).total_seconds() >= f.settle_window_s

    def _reset(self, checks: list[InfoFetcher]) -> None:
        for f in checks:
            self._since[f] = None
