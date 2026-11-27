from datetime import UTC, datetime, timedelta

import pytest
from mocks.fetchers import MockScalingFetcher, MockTransportCollector

from ak_bench.config import HostSettings
from ak_bench.fetchers.core.scaling import CountSample, ScalingInfo
from ak_bench.fetchers.core.transport import QueueDepth, QueueInfo
from ak_bench.run.fetcher_invoker import FetcherInvoker
from ak_bench.run.run_log import RunLog
from ak_bench.run.step_end_check import StepEnd, StepEndCheck

T0 = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)


def at(s: float) -> datetime:
    return T0 + timedelta(seconds=s)


def queue(waiting: int) -> QueueInfo:
    return QueueInfo([QueueDepth(T0, "input", waiting, 0)])


def running(value: int) -> ScalingInfo:
    return ScalingInfo([CountSample(T0, "agent", "running", value)])


@pytest.fixture
def run_log(tmp_path) -> RunLog:
    return RunLog(tmp_path / "run.log", "step")


@pytest.fixture
def invoker(run_info, deployment, run_log) -> FetcherInvoker:
    return FetcherInvoker(run_info, deployment, run_log)


def check(invoker, checks, settled=lambda: True, max_cooldown_s=100.0) -> StepEndCheck:
    c = StepEndCheck(checks, invoker, settled, lookback_s=30, max_cooldown_s=max_cooldown_s)
    c.start(at(0))
    return c


def test_order_requests_then_checks_in_list_order(invoker):
    transport = MockTransportCollector("transport", [queue(0), queue(3), queue(0), queue(0)])  # first is the starting value
    scaling = MockScalingFetcher("scaling", [running(1), running(1)])
    pending = [True]
    c = check(invoker, [transport, scaling], settled=lambda: not pending[0])
    assert len(transport.calls) == len(scaling.calls) == 1  # starting values

    assert c.poll(at(1), at(0)) is None  # requests not settled: no check read
    assert len(transport.calls) == len(scaling.calls) == 1

    pending[0] = False
    assert c.poll(at(2), at(0)) is None  # transport still has waiting messages: scaling not read
    assert len(transport.calls) == 2 and len(scaling.calls) == 1

    assert c.poll(at(3), at(0)) == StepEnd(at(3), max_reached=False)
    assert transport.calls[-1] == (at(3) - timedelta(seconds=30), at(3))  # (now - lookback, now)


def test_settle_window_needs_consecutive_ok_polls(invoker):
    transport = MockTransportCollector("transport", [queue(0)] * 5, settle_window_s=2)
    c = check(invoker, [transport])
    assert c.poll(at(1), at(0)) is None  # run starts
    assert c.poll(at(2), at(0)) is None  # held 1 s
    assert c.poll(at(3), at(0)) == StepEnd(at(3), False)  # held 2 s


def test_not_settled_poll_restarts_the_window(invoker):
    transport = MockTransportCollector("transport", [queue(0), queue(0), queue(1), queue(0), queue(0)], settle_window_s=1)
    c = check(invoker, [transport])
    assert c.poll(at(1), at(0)) is None
    assert c.poll(at(2), at(0)) is None  # waiting > 0: run reset
    assert c.poll(at(3), at(0)) is None  # run restarts here
    assert c.poll(at(4), at(0)) == StepEnd(at(4), False)


@pytest.mark.parametrize(
    "bad, logged",
    [
        (RuntimeError("cloud down"), "fetcher transport in cooldown_checks failed: RuntimeError: cloud down"),
        (QueueInfo(), "transport: no value in cool-down read"),
    ],
    ids=["raising", "empty"],
)
def test_failed_read_resets_the_run_and_logs(invoker, run_log, bad, logged):
    transport = MockTransportCollector("transport", [queue(0), queue(0), bad, queue(0), queue(0)], settle_window_s=1)
    c = check(invoker, [transport])
    assert c.poll(at(1), at(0)) is None
    assert c.poll(at(2), at(0)) is None
    assert c.poll(at(3), at(0)) is None  # would have held without the bad read
    assert c.poll(at(4), at(0)) == StepEnd(at(4), False)
    assert logged in run_log.path.read_text()


def test_earlier_failure_resets_later_runs(invoker):
    transport = MockTransportCollector("transport", [queue(0), queue(0), queue(1), queue(0), queue(0)])
    scaling = MockScalingFetcher("scaling", [running(1)] * 5, settle_window_s=1)
    c = check(invoker, [transport, scaling])
    assert c.poll(at(1), at(0)) is None  # scaling's run starts
    assert c.poll(at(2), at(0)) is None  # transport fails: scaling not read, its run reset
    assert c.poll(at(3), at(0)) is None  # scaling's run restarts
    assert c.poll(at(4), at(0)) == StepEnd(at(4), False)


@pytest.mark.parametrize(
    "f",
    [
        MockScalingFetcher("scaling", [ScalingInfo(), running(1)]),
        MockTransportCollector("transport", [QueueInfo(), queue(0)]),  # its is_settled() ignores the start, so this is the runner's rule
    ],
    ids=["scaling", "transport"],
)
def test_no_starting_value_is_logged_and_never_settles(invoker, run_log, f):
    c = check(invoker, [f])
    assert f"{f.name}: no starting value" in run_log.path.read_text()
    assert c.poll(at(1), at(0)) is None
    assert c.poll(at(101), at(0)) == StepEnd(at(101), max_reached=True)


def test_empty_checks_end_once_requests_settle(invoker):
    pending = [True]
    c = check(invoker, [], settled=lambda: not pending[0])
    assert c.poll(at(1), at(0)) is None
    pending[0] = False
    assert c.poll(at(2), at(0)) == StepEnd(at(2), False)


def test_max_cooldown_with_host_override(invoker, fast_config):
    fast_config.host_settings["mock"] = HostSettings(max_cooldown_s=5)
    failing = MockTransportCollector("transport", [RuntimeError("down")] * 10)
    c = check(invoker, [failing], settled=lambda: False, max_cooldown_s=fast_config.max_cooldown_for("mock"))
    assert c.poll(at(14), at(10)) is None
    assert c.poll(at(15), at(10)) == StepEnd(at(15), max_reached=True)
