import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ak_bench.load.driver.base import ClientDriver
from ak_bench.load.records import RequestRecord, RequestStatus, ResponseEvent
from ak_bench.load.schedule import BurstSchedule, SteadySchedule
from ak_bench.load.token import TokenSigner
from ak_bench.run.run_log import RunLog


@dataclass
class LoadResult:
    records: list[RequestRecord]
    t_load_up: datetime  # first send
    t_load_down: datetime  # steady: t_load_up + load_time_s; burst: last response or timeout
    time_to_answer_all_s: float | None  # burst only


class LoadGenerator:
    """N clients (client i = user bench-i, its own token, driver and session) sending one step's load."""

    TIMEOUT_CHECK_S = 0.5

    def __init__(self, driver_cls: type[ClientDriver], endpoint: str, signer: TokenSigner, clients: int, client_timeout_s: float, run_log: RunLog):
        self.client_timeout_s = client_timeout_s
        self.run_log = run_log
        self.users = [TokenSigner.user(i) for i in range(1, clients + 1)]
        self.sessions = [f"{user}-{uuid4().hex[:12]}" for user in self.users]
        self.drivers = [driver_cls(endpoint, signer.token(user), self._on_event) for user in self.users]
        self._connect_errors: list[BaseException | None] = [None] * clients
        self._records: dict[str, RequestRecord] = {}
        self._waiting: dict[str, RequestRecord] = {}  # sent, no status yet
        self._pending = 0
        self._all_settled = asyncio.Event()
        self._last_settle_mono: float | None = None
        self._tasks: list[asyncio.Task] = []
        self._base_wall = datetime.now(UTC)
        self._base_mono = time.monotonic()

    async def connect(self) -> None:
        """Every client's connect(), gathered; a failed client is kept and its requests end as errors."""
        results = await asyncio.gather(*(d.connect() for d in self.drivers), return_exceptions=True)
        self._connect_errors = [r if isinstance(r, BaseException) else None for r in results]
        failed = [e for e in self._connect_errors if e is not None]
        if failed:
            self.run_log.warning(
                f"{len(failed)} of {len(self.drivers)} clients failed to connect; first error: {type(failed[0]).__name__}: {failed[0]}"
            )

    async def run(self, schedule: BurstSchedule | SteadySchedule, test_type: str) -> LoadResult:
        self._base_wall, self._base_mono = datetime.now(UTC), time.monotonic()
        plans: list[list[tuple[float, RequestRecord]]] = []
        for i, user in enumerate(self.users):
            plan = []
            for offset in schedule.offsets(i + 1):
                request_id = uuid4().hex
                record = RequestRecord(request_id, self.sessions[i], user, self._wall(self._base_mono + offset))
                self._records[request_id] = record
                plan.append((self._base_mono + offset, record))
            plans.append(plan)
        self._pending = len(self._records)
        self._tasks = [asyncio.create_task(self._send_all(i, plan)) for i, plan in enumerate(plans)]
        self._tasks.append(asyncio.create_task(self._watch_timeouts()))

        if test_type == "burst":
            await self._all_settled.wait()
            first_mono = self._first_sent_mono()
            t_load_up = self._wall(first_mono if first_mono is not None else self._base_mono)
            t_load_down = self._wall(self._last_settle_mono)
            to_all = self._last_settle_mono - first_mono if first_mono is not None else None
            return LoadResult(list(self._records.values()), t_load_up, t_load_down, to_all)

        await self._sleep_until(self._base_mono + schedule.load_time_s)
        first_mono = self._first_sent_mono()
        load_up_mono = first_mono if first_mono is not None else self._base_mono
        # t_load_down is counted from the first send, so return no earlier than that, or the cool-down could start before it.
        await self._sleep_until(load_up_mono + schedule.load_time_s)
        t_load_up = self._wall(load_up_mono)
        # Late replies and timeouts keep updating the records until close().
        return LoadResult(list(self._records.values()), t_load_up, t_load_up + timedelta(seconds=schedule.load_time_s), None)

    def all_settled(self) -> bool:
        return self._pending == 0

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await asyncio.gather(*(d.close() for d in self.drivers), return_exceptions=True)

    async def _send_all(self, client: int, plan: list[tuple[float, RequestRecord]]) -> None:
        driver, connect_error = self.drivers[client], self._connect_errors[client]
        for scheduled_mono, record in plan:
            # Each send waits for its own scheduled time, so a late send never shifts later ones.
            await self._sleep_until(scheduled_mono)
            if connect_error is not None:
                self._settle(record, RequestStatus.ERROR, f"connect failed: {type(connect_error).__name__}: {connect_error}")
                continue
            try:
                await driver.send(record.request_id, record.session_id, record.request_id)
            except Exception as e:  # noqa: BLE001 - a failed send is that request's error, never the step's
                self._settle(record, RequestStatus.ERROR, f"send failed: {type(e).__name__}: {e}")
                continue
            record.sent_mono = time.monotonic()
            record.sent = self._wall(record.sent_mono)
            if record.status is None:
                self._waiting[record.request_id] = record

    async def _watch_timeouts(self) -> None:
        while True:
            await asyncio.sleep(self.TIMEOUT_CHECK_S)
            now = time.monotonic()
            for record in list(self._waiting.values()):
                if now >= record.sent_mono + self.client_timeout_s:
                    self._settle(record, RequestStatus.TIMEOUT, f"no response within {self.client_timeout_s} s", now)

    def _on_event(self, event: ResponseEvent) -> None:
        record = self._records.get(event.request_id)
        if record is None or record.status is not None:
            return  # late reply after a timeout, or a duplicate
        if event.kind == "first_chunk":
            if record.first_chunk_mono is None:
                record.first_chunk_mono, record.first_chunk = event.mono, self._wall(event.mono)
        elif event.kind == "complete":
            record.complete_mono, record.complete = event.mono, self._wall(event.mono)
            self._settle(record, RequestStatus.OK, mono=event.mono)
        else:
            self._settle(record, RequestStatus.ERROR, event.detail, event.mono)

    def _settle(self, record: RequestRecord, status: RequestStatus, error: str | None = None, mono: float | None = None) -> None:
        record.status, record.error = status, error
        record.settled_mono = time.monotonic() if mono is None else mono
        record.settled = self._wall(record.settled_mono)
        self._waiting.pop(record.request_id, None)
        self._last_settle_mono = max(self._last_settle_mono or record.settled_mono, record.settled_mono)
        self._pending -= 1
        if self._pending == 0:
            self._all_settled.set()

    def _first_sent_mono(self) -> float | None:
        return min((r.sent_mono for r in self._records.values() if r.sent_mono is not None), default=None)

    def _wall(self, mono: float) -> datetime:
        """Wall time on the step's monotonic base, so windows and durations agree."""
        return self._base_wall + timedelta(seconds=mono - self._base_mono)

    @staticmethod
    async def _sleep_until(mono: float) -> None:
        delay = mono - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
