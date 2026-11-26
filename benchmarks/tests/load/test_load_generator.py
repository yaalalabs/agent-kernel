import asyncio
import random
import time
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest
from mocks.ws_server import MockWsServer

from ak_bench.load.driver.base import ClientDriver
from ak_bench.load.driver.ws_complete import WebSocketCompleteDriver
from ak_bench.load.generator import LoadGenerator
from ak_bench.load.records import RequestStatus, ResponseEvent
from ak_bench.load.schedule import BurstSchedule, SteadySchedule
from ak_bench.load.token import TokenSigner
from ak_bench.run.run_log import RunLog

SECRET = "s3cret"


@pytest.fixture
def run_log(tmp_path) -> RunLog:
    return RunLog(tmp_path / "run.log", "step")


def generator(server: MockWsServer, run_log: RunLog, clients: int, client_timeout_s: float = 2.0) -> LoadGenerator:
    return LoadGenerator(WebSocketCompleteDriver, server.url, TokenSigner(SECRET), clients, client_timeout_s, run_log)


@pytest.mark.asyncio
async def test_burst_one_request_per_client(run_log):
    async with MockWsServer(SECRET, delay_s=0.1) as server:
        gen = generator(server, run_log, 5)
        await gen.connect()
        assert server.connections == {f"bench-{i}": 1 for i in range(1, 6)}  # every connect done before run()
        result = await gen.run(BurstSchedule(), "burst")
        await gen.close()

    assert gen.all_settled()
    assert server.frames == {f"bench-{i}": 1 for i in range(1, 6)}
    tokens = {parse_qs(urlsplit(p).query)["token"][0] for p in server.paths}
    assert len(tokens) == 5
    arrivals = [mono for _, _, mono in server.received]
    assert max(arrivals) - min(arrivals) < 0.05
    ids = [r.request_id for r in result.records]
    assert len(set(ids)) == 5
    assert all(frame["body"]["prompt"] == frame["request_id"] for _, frame, _ in server.received)
    assert {r.user_id for r in result.records} == {f"bench-{i}" for i in range(1, 6)}
    assert len({r.session_id for r in result.records}) == 5
    for r in result.records:
        assert r.status == RequestStatus.OK
        assert 0.1 <= r.latency_s < 0.5
        assert r.first_chunk == r.complete and r.sent <= r.complete
    assert result.t_load_up == min(r.sent for r in result.records)
    assert result.t_load_down == max(r.complete for r in result.records)


@pytest.mark.asyncio
async def test_dropped_reply_times_out(run_log, monkeypatch):
    monkeypatch.setattr(LoadGenerator, "TIMEOUT_CHECK_S", 0.05)
    async with MockWsServer(SECRET, drop={"bench-2"}) as server:
        gen = generator(server, run_log, 3, client_timeout_s=0.3)
        await gen.connect()
        result = await gen.run(BurstSchedule(), "burst")
        await gen.close()
    by_user = {r.user_id: r for r in result.records}
    assert by_user["bench-2"].status == RequestStatus.TIMEOUT
    assert 0.3 <= by_user["bench-2"].settled_mono - by_user["bench-2"].sent_mono < 0.45
    assert by_user["bench-2"].latency_s is None
    assert by_user["bench-1"].status == by_user["bench-3"].status == RequestStatus.OK


@pytest.mark.asyncio
async def test_refused_connect_errors_only_that_client(run_log):
    async with MockWsServer(SECRET, fail_connect_for={"bench-2"}) as server:
        gen = generator(server, run_log, 3)
        await gen.connect()
        result = await gen.run(BurstSchedule(), "burst")
        await gen.close()
    by_user = {r.user_id: r for r in result.records}
    assert by_user["bench-2"].status == RequestStatus.ERROR and by_user["bench-2"].sent is None
    assert "connect failed" in by_user["bench-2"].error
    assert by_user["bench-1"].status == by_user["bench-3"].status == RequestStatus.OK
    assert "1 of 3 clients failed to connect" in run_log.path.read_text()


@pytest.mark.asyncio
async def test_steady_returns_after_load_time_and_keeps_updating(run_log):
    async with MockWsServer(SECRET, delay_s=0.15) as server:
        gen = generator(server, run_log, 2)
        await gen.connect()
        started = time.monotonic()
        result = await gen.run(SteadySchedule(0.1, 0.1, 0.35, random.Random(1)), "steady")
        assert 0.35 <= time.monotonic() - started < 0.45
        assert (result.t_load_down - result.t_load_up).total_seconds() == pytest.approx(0.35)
        assert not gen.all_settled()  # the last sends' replies are still in flight
        await asyncio.sleep(0.3)
        assert gen.all_settled()
        await gen.close()
    assert len(result.records) == 8
    assert all(r.status == RequestStatus.OK for r in result.records)


class SlowFirstSendDriver(ClientDriver):
    """The first send takes 0.25 s; every request is answered as soon as it is written."""

    trace_stages = ()

    async def connect(self) -> None:
        self.sends = 0

    async def send(self, request_id: str, session_id: str, prompt: str) -> None:
        self.sends += 1
        if self.sends == 1:
            await asyncio.sleep(0.25)
        asyncio.get_running_loop().call_soon(lambda: self.on_event(ResponseEvent(request_id, "complete", datetime.now(UTC), time.monotonic())))

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_late_send_does_not_shift_later_sends(run_log):
    gen = LoadGenerator(SlowFirstSendDriver, "unused", TokenSigner(SECRET), 1, 2.0, run_log)
    await gen.connect()
    result = await gen.run(SteadySchedule(0.2, 0.2, 0.65, random.Random()), "steady")
    await asyncio.sleep(0.05)
    await gen.close()
    base = result.records[0].scheduled_send
    sent = [(r.sent - base).total_seconds() for r in result.records]
    assert sent[0] == pytest.approx(0.0, abs=0.03)  # sent is taken as the send starts; this one takes 0.25 s
    assert sent[1] == pytest.approx(0.25, abs=0.03)  # was due at 0.2: sent at once, not 0.2 after the late one
    assert sent[2] == pytest.approx(0.4, abs=0.03)
    assert sent[3] == pytest.approx(0.6, abs=0.03)
    assert all(r.status == RequestStatus.OK and r.latency_s >= 0 for r in result.records)
