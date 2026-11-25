import csv
import threading
from datetime import UTC, datetime, timedelta

from agentkernel.core import TraceStage
from mocks.fetchers import MockCostFetcher, MockResourceFetcher, MockScalingFetcher, MockTraceCollector, MockTransportCollector

from ak_bench.fetchers.core.cost import CostInfo, CostItem
from ak_bench.fetchers.core.resources import ResourceSample, ResourceUsage
from ak_bench.fetchers.core.scaling import CountSample, ScalingInfo, WorkerSpan
from ak_bench.fetchers.core.trace import TraceInfo
from ak_bench.fetchers.core.transport import QueueDepth, QueueInfo
from ak_bench.results.common.keyed_csv import KeyedCsv

T0 = datetime(2026, 11, 23, 10, 4, tzinfo=UTC)
T1 = T0 + timedelta(seconds=1, milliseconds=5)


def rows(path):
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def test_scaling_writes_samples_and_spans_latest_span_wins(tmp_path):
    f = MockScalingFetcher("scaling")
    f.store(ScalingInfo([CountSample(T0, "api", "running", 1)], [WorkerSpan("api", "w1", T0, None)]), tmp_path)
    f.store(ScalingInfo([CountSample(T0, "api", "running", 2)], [WorkerSpan("api", "w1", T0, T1, {"b": 2, "a": 1})]), tmp_path)

    columns, samples = rows(tmp_path / "scaling-samples.csv")
    assert columns == ["ts", "tier", "count_type", "value", "fetcher"]
    assert samples == [{"ts": "2026-11-23T10:04:00.000Z", "tier": "api", "count_type": "running", "value": "2", "fetcher": "scaling"}]
    columns, spans = rows(tmp_path / "worker-spans.csv")
    assert columns == ["tier", "worker", "started", "stopped", "extra", "fetcher"]
    assert spans == [
        {
            "tier": "api",
            "worker": "w1",
            "started": "2026-11-23T10:04:00.000Z",
            "stopped": "2026-11-23T10:04:01.005Z",
            "extra": '{"a":1,"b":2}',
            "fetcher": "scaling",
        }
    ]


def test_resource_none_worker_is_empty_cell_and_key_replaces(tmp_path):
    f = MockResourceFetcher("resource")
    f.store(
        ResourceUsage([ResourceSample(T0, "api", None, "cpu_pct", "max", 10.0), ResourceSample(T1, "api", "w1", "cpu_pct", "max", 5.0)]), tmp_path
    )
    f.store(ResourceUsage([ResourceSample(T0, "api", None, "cpu_pct", "max", 20.0)]), tmp_path)

    columns, data = rows(tmp_path / "resource-usage.csv")
    assert columns == ["ts", "tier", "worker", "metric", "stat", "value", "fetcher"]
    assert [(r["worker"], r["value"]) for r in data] == [("", "20.0"), ("w1", "5.0")]


def test_trace_writes_one_row_per_request_stage(tmp_path):
    f = MockTraceCollector("trace")
    f.store(TraceInfo({"r1": {TraceStage.REQUEST_RECEIVED: T0, TraceStage.AGENT_DONE: T0}}), tmp_path)
    f.store(TraceInfo({"r1": {TraceStage.AGENT_DONE: T1}}), tmp_path)

    columns, data = rows(tmp_path / "stage-timestamps.csv")
    assert columns == ["request_id", "stage", "ts"]
    assert data == [
        {"request_id": "r1", "stage": "REQUEST_RECEIVED", "ts": "2026-11-23T10:04:00.000Z"},
        {"request_id": "r1", "stage": "AGENT_DONE", "ts": "2026-11-23T10:04:01.005Z"},
    ]


def test_transport_key_replaces(tmp_path):
    f = MockTransportCollector("sqs")
    f.store(QueueInfo([QueueDepth(T0, "input", 5, 1)]), tmp_path)
    f.store(QueueInfo([QueueDepth(T0, "input", 0, 0), QueueDepth(T0, "output", 2, 0)]), tmp_path)

    columns, data = rows(tmp_path / "queue-depth.csv")
    assert columns == ["ts", "queue", "waiting", "in_flight", "fetcher"]
    assert [(r["queue"], r["waiting"], r["in_flight"]) for r in data] == [("input", "0", "0"), ("output", "2", "0")]


def test_cost_key_replaces(tmp_path):
    f = MockCostFetcher("cost")
    f.store(CostInfo([CostItem(T0, T1, "ECS", 1.5, "UnblendedCost")]), tmp_path)
    f.store(CostInfo([CostItem(T0, T1, "ECS", 2.5, "UnblendedCost")]), tmp_path)

    columns, data = rows(tmp_path / "cost.csv")
    assert columns == ["period_start", "period_end", "service", "usd", "metric", "fetcher"]
    assert [r["usd"] for r in data] == ["2.5"]


def test_two_fetchers_same_file_keep_their_own_rows(tmp_path):
    MockTransportCollector("a").store(QueueInfo([QueueDepth(T0, "input", 1, 0)]), tmp_path)
    MockTransportCollector("b").store(QueueInfo([QueueDepth(T0, "input", 2, 0)]), tmp_path)
    assert [r["fetcher"] for r in rows(tmp_path / "queue-depth.csv")[1]] == ["a", "b"]


def test_two_threads_storing_500_rows_each_lose_none(tmp_path):
    def store(name):
        f = MockTransportCollector(name)
        for i in range(500):
            f.store(QueueInfo([QueueDepth(T0 + timedelta(seconds=i), "input", i, 0)]), tmp_path)

    threads = [threading.Thread(target=store, args=(name,)) for name in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    data = rows(tmp_path / "queue-depth.csv")[1]
    assert len(data) == 1000
    assert len({(r["ts"], r["fetcher"]) for r in data}) == 1000
    assert not (tmp_path / "queue-depth.csv.tmp").exists()


def test_keyed_csv_read_missing_file_is_empty(tmp_path):
    assert KeyedCsv(tmp_path / "none.csv", ["a"], ["a"]).read() == []
