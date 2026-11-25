import threading
from datetime import UTC, datetime, timedelta

import pytest
from mocks.fetchers import MockResourceFetcher, MockScalingFetcher, MockTraceCollector, MockTransportCollector, RaisingFetcher
from mocks.ws_server import MockWsServer

from ak_bench.config import HostSettings
from ak_bench.fetchers.core.stage_fetchers import StageFetchers
from ak_bench.fetchers.core.transport import QueueDepth, QueueInfo
from ak_bench.hosts.host import Deployment, Host
from ak_bench.load.generator import LoadGenerator
from ak_bench.load.records import RequestStatus
from ak_bench.run.fetcher_invoker import FetcherInvoker
from ak_bench.run.run_log import RunLog
from ak_bench.run.step_runner import StepRunner

SECRET = "s3cret"


class IdleTransport(MockTransportCollector):
    """Always reports an empty queue, so the cool-down check holds."""

    def fetch(self, run, deployment, start, end):
        self.calls.append((start, end))
        return QueueInfo([QueueDepth(end, "input", 0, 0)])


class TimedTrace(MockTraceCollector):
    def fetch(self, run, deployment, start, end):
        self.called_at = datetime.now(UTC)
        return super().fetch(run, deployment, start, end)


class HangingFetcher(MockResourceFetcher):
    """Answers the first poll, then blocks until released."""

    release = threading.Event()

    def fetch(self, run, deployment, start, end):
        if self.calls:
            self.release.wait(5)
        return super().fetch(run, deployment, start, end)


@pytest.fixture
def run_log(tmp_path) -> RunLog:
    return RunLog(tmp_path / "run.log", "step")


async def run_step(fast_config, run_info, run_log, tmp_path, fetchers: StageFetchers, test_type="steady", step=2, **server_kw):
    async with MockWsServer(SECRET, delay_s=0.05, **server_kw) as server:
        deployment = Deployment(server.url, {}, {"input": {}, "output": {}}, {}, {})
        runner = StepRunner(fast_config, Host("mock", fetchers), FetcherInvoker(run_info, deployment, run_log), run_log)
        return await runner.run(run_info, deployment, SECRET, test_type, step, tmp_path / "step")


@pytest.mark.asyncio
async def test_steady_step_timeline(fast_config, run_info, run_log, tmp_path, monkeypatch):
    connected = []
    connect = LoadGenerator.connect

    async def record_connect(self):
        await connect(self)
        connected.append(datetime.now(UTC))

    monkeypatch.setattr(LoadGenerator, "connect", record_connect)
    tracker, idle, trace = MockScalingFetcher("tracker"), IdleTransport("transport"), TimedTrace("trace")
    record = await run_step(fast_config, run_info, run_log, tmp_path, StageFetchers(during_step=[tracker], cooldown_checks=[idle], after_step=[trace]))

    assert connected[0] <= record.started  # connect happens before `before` starts
    assert record.started <= record.before_end <= record.t_load_up <= record.t_load_down <= record.ended
    assert (record.before_end - record.started).total_seconds() >= 0.2
    assert not record.cooldown_max_reached and record.timed_out == 0 and record.seed is not None
    assert all(r.status == RequestStatus.OK for r in record.load.records)

    # during_step: contiguous (last poll, now) windows from the step start, with a final poll after the stop
    assert tracker.calls[0][0] == record.started
    assert all(prev[1] == nxt[0] for prev, nxt in zip(tracker.calls, tracker.calls[1:]))
    assert tracker.calls[-1][1] >= record.ended

    # after_step: (step start, step end), after the wait
    assert trace.calls == [(record.started, record.ended)]
    assert trace.called_at - record.ended >= timedelta(seconds=fast_config.step_run.after_step_wait_s)


@pytest.mark.asyncio
async def test_burst_step_has_no_seed(fast_config, run_info, run_log, tmp_path):
    record = await run_step(fast_config, run_info, run_log, tmp_path, StageFetchers(), test_type="burst", step=3)
    assert record.seed is None and len(record.load.records) == 3
    assert record.load.time_to_answer_all_s is not None


@pytest.mark.asyncio
async def test_hanging_tracker_is_cancelled(fast_config, run_info, run_log, tmp_path, monkeypatch):
    monkeypatch.setattr(StepRunner, "STOP_TIMEOUT_S", 0.2)
    HangingFetcher.release.clear()
    try:
        record = await run_step(fast_config, run_info, run_log, tmp_path, StageFetchers(during_step=[HangingFetcher("stuck")]), test_type="burst")
    finally:
        HangingFetcher.release.set()
    assert record.ended
    assert "tracking of fetcher stuck did not stop within 0.2 s; cancelled" in run_log.path.read_text()


@pytest.mark.asyncio
async def test_raising_after_step_fetcher_is_logged_and_step_completes(fast_config, run_info, run_log, tmp_path):
    resource = MockResourceFetcher("resource")
    record = await run_step(fast_config, run_info, run_log, tmp_path, StageFetchers(after_step=[RaisingFetcher("broken"), resource]), test_type="burst")
    assert record.ended and len(resource.calls) == 1  # the next fetcher still ran
    assert "fetcher broken in after_step failed: RuntimeError: broken is broken" in run_log.path.read_text()


@pytest.mark.asyncio
async def test_missing_responses_warning(fast_config, run_info, run_log, tmp_path, monkeypatch):
    monkeypatch.setattr(LoadGenerator, "TIMEOUT_CHECK_S", 0.05)
    fast_config.step_run.client_timeout_s = 0.3
    record = await run_step(fast_config, run_info, run_log, tmp_path, StageFetchers(), test_type="burst", step=3, drop={"bench-2"})
    assert record.timed_out == 1
    assert "responses for 1 requests were not received within the timeout of 0.3 s" in run_log.path.read_text()


@pytest.mark.asyncio
async def test_max_cooldown_ends_the_step(fast_config, run_info, run_log, tmp_path):
    fast_config.host_settings["mock"] = HostSettings(max_cooldown_s=0.3)
    busy = MockTransportCollector("transport", [QueueInfo([QueueDepth(datetime.now(UTC), "input", 5, 0)])] * 100)
    record = await run_step(fast_config, run_info, run_log, tmp_path, StageFetchers(cooldown_checks=[busy]), test_type="burst")
    assert record.cooldown_max_reached
    assert (record.ended - record.t_load_down).total_seconds() >= 0.3
