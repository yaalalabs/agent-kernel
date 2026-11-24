import asyncio
import contextlib
import random
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ak_bench.config import BenchConfig
from ak_bench.load.driver.factory import DriverFactory
from ak_bench.load.generator import LoadGenerator, LoadResult
from ak_bench.load.records import RequestStatus
from ak_bench.load.schedule import BurstSchedule, SteadySchedule
from ak_bench.load.token import TokenSigner
from ak_bench.platforms.base import Deployment, Host, InfoFetcher, RunInfo
from ak_bench.run.fetcher_invoker import FetcherInvoker
from ak_bench.run.run_log import RunLog
from ak_bench.run.step_end_check import StepEndCheck


@dataclass
class StepRecord:
    test_type: str
    step: int
    started: datetime
    before_end: datetime
    t_load_up: datetime
    t_load_down: datetime
    ended: datetime
    cooldown_max_reached: bool
    load: LoadResult
    timed_out: int
    seed: int | None  # steady schedule seed for step-metadata.json; None for burst


class StepRunner:
    """Runs one step: connect → before → load → cool-down → wait + fetch (#786 Step timeline)."""

    STOP_TIMEOUT_S = 30

    def __init__(self, config: BenchConfig, host: Host, invoker: FetcherInvoker, run_log: RunLog):
        self.config = config
        self.host = host
        self.invoker = invoker
        self.run_log = run_log

    async def run(self, run: RunInfo, deployment: Deployment, secret: str, test_type: str, step: int, step_dir: Path) -> StepRecord:
        cfg, fetchers = self.config.step_run, self.host.fetchers
        step_dir.mkdir(parents=True, exist_ok=True)
        gen = LoadGenerator(
            DriverFactory.driver_class(run.mode, run.message_type), deployment.endpoint, TokenSigner(secret), step, cfg.client_timeout_s, self.run_log
        )
        stop, trackers = asyncio.Event(), {}
        try:
            await gen.connect()
            started = self._now()
            trackers = {asyncio.create_task(self._track(f, started, stop, step_dir)): f for f in fetchers.during_step}
            await asyncio.sleep(cfg.before_window_s)
            before_end = self._now()
            check = StepEndCheck(
                fetchers.cooldown_checks, self.invoker, gen.all_settled, cfg.cooldown_lookback_s, self.config.max_cooldown_for(run.host)
            )
            await asyncio.to_thread(check.start, before_end)

            seed, schedule = self._schedule(test_type)
            load = await gen.run(schedule, test_type)

            while (end := await asyncio.to_thread(check.poll, self._now(), load.t_load_down)) is None:
                await asyncio.sleep(cfg.cooldown_poll_interval_s)
            await self._stop_tracking(stop, trackers)
        finally:
            # Only does anything when the step failed or was interrupted before the tracking stopped.
            for task in trackers:
                task.cancel()
            await asyncio.gather(*trackers, return_exceptions=True)
            await gen.close()

        await asyncio.sleep(cfg.after_step_wait_s)
        for f in fetchers.after_step:
            await asyncio.to_thread(self.invoker.fetch_and_store, f, "after_step", started, end.at, step_dir)

        timed_out = sum(r.status == RequestStatus.TIMEOUT for r in load.records)
        if timed_out:
            self.run_log.warning(f"responses for {timed_out} requests were not received within the timeout of {cfg.client_timeout_s} s")
        return StepRecord(test_type, step, started, before_end, load.t_load_up, load.t_load_down, end.at, end.max_reached, load, timed_out, seed)

    async def _track(self, f: InfoFetcher, started: datetime, stop: asyncio.Event, step_dir: Path) -> None:
        """Polls (last poll, now) every poll interval; once stopped, one last poll, so nothing is fetched twice or missed."""
        last, interval = started, f.poll_interval_s or self.config.fetchers.poll_interval_for(f.name)
        while True:
            stopped = stop.is_set()  # read before the fetch, so a stop during a fetch still gets its final poll
            now = self._now()
            await asyncio.to_thread(self.invoker.fetch_and_store, f, "during_step", last, now, step_dir)
            last = now
            if stopped:
                return
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), interval)

    async def _stop_tracking(self, stop: asyncio.Event, trackers: dict[asyncio.Task, InfoFetcher]) -> None:
        stop.set()
        if not trackers:
            return
        _, pending = await asyncio.wait(trackers, timeout=self.STOP_TIMEOUT_S)
        for task in pending:
            # The worker thread finishes on its own; its result is discarded.
            task.cancel()
            self.run_log.warning(f"tracking of fetcher {trackers[task].name} did not stop within {self.STOP_TIMEOUT_S} s; cancelled")

    def _schedule(self, test_type: str) -> tuple[int | None, BurstSchedule | SteadySchedule]:
        if test_type == "burst":
            return None, BurstSchedule()
        seed, traffic = secrets.randbits(64), self.config.steady_traffic
        return seed, SteadySchedule(traffic.min_send_interval_s, traffic.max_send_interval_s, traffic.load_time_s, random.Random(seed))

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)
