from datetime import UTC, datetime, timedelta

import pytest
from mocks.fetchers import MockScalingFetcher, MockTransportCollector

from ak_bench.fetchers.core.scaling import CountSample, ScalingInfo
from ak_bench.fetchers.core.transport import QueueDepth, QueueInfo

T0 = datetime(2026, 11, 23, 10, 0, tzinfo=UTC)
T1 = T0 + timedelta(seconds=10)


def running(*samples):
    return ScalingInfo([CountSample(ts, tier, "running", value) for ts, tier, value in samples])


SCALING = MockScalingFetcher("scaling")
TRANSPORT = MockTransportCollector("transport")


@pytest.mark.parametrize(
    ("now", "start", "settled"),
    [
        (running((T0, "api", 2)), running((T0, "api", 2)), True),
        (running((T0, "api", 3)), running((T0, "api", 2)), False),
        (running((T0, "agent", 2)), running((T0, "api", 2), (T0, "agent", 2)), False),
        (running((T0, "api", 2)), None, False),
        # latest sample by ts wins, in both reads
        (running((T1, "api", 2), (T0, "api", 5)), running((T0, "api", 9), (T1, "api", 2)), True),
    ],
    ids=["equal", "higher", "missing-tier", "start-failed", "latest-wins"],
)
def test_scaling_is_settled(now, start, settled):
    assert SCALING.is_settled(now, start) is settled


def test_scaling_ignores_other_count_types_and_has_value():
    desired = ScalingInfo([CountSample(T0, "api", "desired", 5)])
    assert SCALING.is_settled(running((T0, "api", 2)), ScalingInfo(desired.samples + running((T0, "api", 2)).samples))
    assert not SCALING.has_value(desired)
    assert SCALING.has_value(running((T0, "api", 1)))


@pytest.mark.parametrize(
    ("samples", "settled"),
    [
        ([QueueDepth(T0, "input", 0, 0)], True),
        ([QueueDepth(T0, "input", 3, 0)], False),
        ([QueueDepth(T0, "input", 0, 1)], False),
        ([QueueDepth(T0, "input", 0, 0), QueueDepth(T0, "output", 1, 0)], False),
        ([QueueDepth(T1, "input", 0, 0), QueueDepth(T0, "input", 4, 4)], True),
        ([QueueDepth(T0, "input", 0, 0), QueueDepth(T1, "input", 4, 0)], False),
    ],
    ids=["zero", "waiting", "in-flight", "multiple-queues", "latest-zero-wins", "latest-busy-wins"],
)
def test_transport_is_settled(samples, settled):
    assert TRANSPORT.is_settled(QueueInfo(samples), None) is settled


def test_transport_has_value():
    assert not TRANSPORT.has_value(QueueInfo())
    assert TRANSPORT.has_value(QueueInfo([QueueDepth(T0, "input", 0, 0)]))
