import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy
import pytest
from mocks.fetchers import MockResourceFetcher, MockScalingFetcher, MockTraceCollector, MockTransportCollector, RaisingFetcher

from ak_bench.config import BenchConfig
from ak_bench.fetchers.core.stage_fetchers import StageFetchers
from ak_bench.hosts.host import Deployment, Host
from ak_bench.load.driver.ws_complete import WebSocketCompleteDriver
from ak_bench.load.generator import LoadResult
from ak_bench.load.records import RequestRecord, RequestStatus
from ak_bench.results.common.keyed_csv import KeyedCsv
from ak_bench.results.common.layout import ResultsLayout
from ak_bench.results.common.percentiles import PERCENTILES, percentiles
from ak_bench.results.csv.per_request import PerRequestWriter
from ak_bench.results.csv.per_window import PerWindowWriter, WindowGrid
from ak_bench.results.csv.resource_columns import ResourceCollector
from ak_bench.results.csv.scaling_numbers import ScalingDerivation
from ak_bench.results.csv.summary import SummaryWriter
from ak_bench.results.metadata import RunMetadataWriter, StepMetadataWriter
from ak_bench.run.step_runner import StepRecord

FIXTURES = Path(__file__).parent.parent / "fixtures" / "step"
T = datetime(2026, 11, 24, 10, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return T + timedelta(seconds=seconds)


@pytest.fixture
def step_dir(tmp_path) -> Path:
    shutil.copytree(FIXTURES, tmp_path / "step-1")
    return tmp_path / "step-1"


@pytest.fixture
def config() -> BenchConfig:
    return BenchConfig.model_validate(
        {"step_run": {"time_window_s": 10}, "fetchers": {"default": {"poll_interval_s": 5}}, "host_settings": {"mock": {"max_cooldown_s": 600}}}
    )


@pytest.fixture
def host() -> Host:
    scaling, transport = MockScalingFetcher("scaling"), MockTransportCollector("transport")
    resource, broken = MockResourceFetcher("resource"), RaisingFetcher("resource2")
    resource.metrics = frozenset({("cpu_pct", "value"), ("mem_pct", "max")})
    broken.metrics = frozenset({("cpu_pct", "max")})
    return Host(
        "mock",
        StageFetchers(during_step=[scaling, transport], cooldown_checks=[transport, scaling], after_step=[MockTraceCollector("trace"), resource, broken]),
    )


@pytest.fixture
def deployment() -> Deployment:
    return Deployment("ws://127.0.0.1:1", {"runner": {}, "api": {}}, {"input": {}, "output": {}}, {}, {"region": "eu-west-1", "memory_mb": 512})


def request(request_id: str, status: RequestStatus, sent: float, done: float) -> RequestRecord:
    """A request sent at `sent` seconds that ended (complete, error or timeout) at `done`."""
    record = RequestRecord(
        request_id, "s-1", "bench-1", at(sent - 0.5), sent=at(sent), status=status, sent_mono=sent, settled_mono=done, settled=at(done)
    )
    if status == RequestStatus.OK:
        record.complete, record.complete_mono = at(done), done
    return record


@pytest.fixture
def record() -> StepRecord:
    records = [
        request("r1", RequestStatus.OK, 12, 15),
        request("r2", RequestStatus.OK, 13, 25),
        request("r3", RequestStatus.ERROR, 14, 14),
        request("r4", RequestStatus.TIMEOUT, 20, 50),
    ]
    load = LoadResult(records, at(10), at(40), None)
    return StepRecord("steady", 1, at(0), at(10), at(10), at(40), at(60), False, load, 1, 42)


def test_percentiles_match_numpy_linear_and_are_empty_for_no_data():
    values = [0.3, 1.0, 2.5, 7.0, 7.1, 40.0, 3.3]
    expected = numpy.percentile(values, PERCENTILES, method="linear")
    assert list(percentiles(values).values()) == pytest.approx(list(expected))
    assert percentiles([]) == {"p0": None, "p25": None, "p50": None, "p75": None, "p99": None, "p100": None}


def test_per_request_durations(step_dir, record):
    rows = {r["request_id"]: r for r in PerRequestWriter(WebSocketCompleteDriver).write(step_dir, record.load.records)}

    r1 = rows["r1"]
    assert r1["latency_s"] == 3
    assert r1["REQUEST_RECEIVED_s"] == pytest.approx(0.5)  # client sent -> REQUEST_RECEIVED
    assert r1["AGENT_DONE_s"] == pytest.approx(1.0)  # AGENT_START -> AGENT_DONE in complete
    assert r1["CLIENT_RECEIVED_s"] == pytest.approx(0.2)  # RESPONSE_DELIVERED -> complete
    assert r1["AGENT_FIRST_CHUNK_s"] is None  # not in the complete chain
    assert rows["r2"]["REQUEST_RECEIVED_s"] is None and rows["r2"]["CLIENT_RECEIVED_s"] is None  # no trace points
    assert rows["r3"]["latency_s"] is None

    written = KeyedCsv(step_dir / "per-request.csv", [], []).read()
    assert written[0]["REQUEST_RECEIVED_ts"] == "2026-11-24T10:00:12.500Z"
    assert written[0]["status"] == "ok" and written[0]["AGENT_FIRST_CHUNK_s"] == ""
    assert "RESPONSE_FOUND_ts" not in written[0] and "RESPONSE_POLL_START_s" not in written[0]


def test_per_window_client_columns(step_dir, record, config, host, deployment):
    rows = PerWindowWriter(config, host, deployment).write(step_dir, record)

    assert [r["step_part"] for r in rows] == ["before", "load", "load", "load", "cooldown", "cooldown"]
    assert [r["tx_per_s"] for r in rows] == pytest.approx([0, 0.3, 0.1, 0, 0, 0])
    assert [r["rx_per_s"] for r in rows] == pytest.approx([0, 0.1, 0.1, 0, 0, 0])
    assert [r["errors"] for r in rows] == [0, 1, 0, 0, 0, 0]
    assert [r["timeouts"] for r in rows] == [0, 0, 0, 0, 0, 1]
    assert [r["latency_p50"] for r in rows] == [None, 3, 12, None, None, None]
    assert (step_dir / "per-time-window.csv").exists()


def test_per_window_carry_forward_limit(step_dir, record, config, host, deployment):
    rows = PerWindowWriter(config, host, deployment).write(step_dir, record)

    # during_step series: carried for at most the poll interval (5 s)
    assert [r["runner.running.scaling"] for r in rows] == [1, 2, 3, 3, 2, 1]
    assert [r["api.running.scaling"] for r in rows] == [None, None, 1, None, None, 1]
    assert [r["input.waiting.transport"] for r in rows] == [0, 8, 4, 0, 0, 0]
    # after_step series: carried for at most the smallest sample gap (10 s); a single sample fills only its own window
    assert [r["runner.cpu_pct.p0.resource"] for r in rows] == [20, 30, 30, 70, 80, 80]
    assert [r["runner.cpu_pct.p100.resource"] for r in rows] == [20, 50, 60, 70, 80, 80]
    assert [r["runner.mem_pct.max.resource"] for r in rows] == [None, None, None, 40, None, None]


def test_per_window_declares_empty_columns_for_a_fetcher_that_stored_nothing(step_dir, record, config, host, deployment):
    rows = PerWindowWriter(config, host, deployment).write(step_dir, record)

    for column in ("runner.cpu_pct.max.resource2", "api.cpu_pct.max.resource2", "api.cpu_pct.p50.resource", "api.desired.scaling"):
        assert [r[column] for r in rows] == [None] * 6
    header = KeyedCsv(step_dir / "per-time-window.csv", [], []).header()
    assert {"runner.cpu_pct.max.resource2", "output.in_flight.transport"} <= set(header)


def test_window_grid_last_window_covers_the_end():
    assert len(WindowGrid(at(0), at(60), 10).windows) == 6
    assert len(WindowGrid(at(0), at(61), 10).windows) == 7
    assert len(WindowGrid(at(0), at(0), 10).windows) == 1


def test_window_grid_boundary_sample_falls_in_the_window_it_starts():
    grid = WindowGrid(at(0), at(0.6), 0.1)  # 0.3 / 0.1 is 2.999... in float seconds
    assert [grid.index(at(k / 10)) for k in range(6)] == [0, 1, 2, 3, 4, 5]
    assert len(grid.windows) == 6


def test_derived_scaling_up_and_down_no_scale_and_backlog(step_dir, record, host, deployment):
    derived = ScalingDerivation(host, deployment).derive(step_dir, record)

    runner = {k.split(".")[1]: v for k, v in derived.items() if k.startswith("runner.")}
    assert runner == {
        "decision_delay_s": 5,
        "first_new_worker_s": 8,  # span started at +18 s, before the running increase at +20 s
        "scale_up_done_s": 15,
        "scale_down_start_s": 5,
        "scale_down_done_s": 15,
        "workers_before_up": 1,
        "workers_peak": 3,
        "workers_before_down": 3,
        "workers_after_down": 1,
        "scale_up_rate_per_min": 8,
        "scale_down_rate_per_min": 8,
    }
    api = {k.split(".")[1]: v for k, v in derived.items() if k.startswith("api.")}
    assert (api["workers_before_up"], api["workers_peak"], api["workers_before_down"], api["workers_after_down"]) == (1, 1, 1, 1)
    assert [api[c] for c in ("decision_delay_s", "first_new_worker_s", "scale_up_done_s", "scale_down_start_s", "scale_down_done_s")] == [None] * 5
    assert api["scale_up_rate_per_min"] is None and api["scale_down_rate_per_min"] is None
    assert derived["input.backlog_drained_s.transport"] == 25
    assert derived["output.backlog_drained_s.transport"] is None


def test_derived_without_a_running_source():
    numbers = ScalingDerivation.tier([], [(at(0), 1), (at(15), 4)], [], at(0), at(10), at(40), at(60))

    assert numbers["decision_delay_s"] == 5
    assert all(v is None for k, v in numbers.items() if k != "decision_delay_s")


def test_resource_summary_over_raw_samples(step_dir, host, deployment):
    summary = ResourceCollector(host, deployment, {}).summary(step_dir, at(0), at(60))

    assert summary["runner.cpu_pct.p0.resource"] == 10 and summary["runner.cpu_pct.p100.resource"] == 80
    assert summary["runner.cpu_pct.p50.resource"] == 50
    assert summary["runner.mem_pct.max.resource"] == 40
    assert summary["runner.cpu_pct.max.resource2"] is None


def test_summary_row_and_replace(tmp_path, step_dir, record, config, host, deployment):
    requests = PerRequestWriter(WebSocketCompleteDriver).write(step_dir, record.load.records)
    windows = PerWindowWriter(config, host, deployment).write(step_dir, record)
    scaling = ScalingDerivation(host, deployment).derive(step_dir, record)
    resources = ResourceCollector(host, deployment, {}).summary(step_dir, record.started, record.ended)
    row = SummaryWriter.build(record, requests, windows, scaling, resources)

    assert (row["requests"], row["ok"], row["errors"], row["timeouts"]) == (4, 2, 1, 1)
    assert row["latency_p50"] == 7.5 and row["latency_n"] == 2
    assert row["REQUEST_RECEIVED_p0"] == pytest.approx(0.5) and row["REQUEST_RECEIVED_n"] == 1
    assert row["CLIENT_RECEIVED_n"] == 1 and row["AGENT_FIRST_CHUNK_n"] == 0
    assert (row["tx_min"], row["tx_max"]) == (0, 0.3) and row["tx_avg"] == pytest.approx(0.08)
    assert row["rx_avg"] == pytest.approx(0.04)
    assert row["time_to_answer_all_s"] is None
    assert row["runner.workers_peak.scaling"] == 3 and row["runner.mem_pct.max.resource"] == 40

    writer, test_type_dir = SummaryWriter(), tmp_path / "steady"
    writer.upsert(test_type_dir, row)
    writer.upsert(test_type_dir, {**row, "step": 2})
    writer.upsert(test_type_dir, {**row, "ok": 3})  # a re-run of step 1 replaces its row
    rows = KeyedCsv(test_type_dir / "summary.csv", [], []).read()
    assert [(r["step"], r["ok"]) for r in rows] == [("1", "3"), ("2", "2")]

    writer.upsert(test_type_dir, {"step": 3, "new.column": 1})  # a later step's new series grows the header
    assert "new.column" in KeyedCsv(test_type_dir / "summary.csv", [], []).header()

    writer.remove(test_type_dir, 2)
    assert [r["step"] for r in KeyedCsv(test_type_dir / "summary.csv", [], []).read()] == ["1", "3"]


def test_run_metadata(tmp_path, run_info, deployment):
    deployment.settings["host"] = "not-the-host"
    RunMetadataWriter().write(tmp_path, run_info, at(0), deployment, (0.5, 2.0))

    data = json.loads((tmp_path / "run-metadata.json").read_text())
    assert data["run_id"] == run_info.run_id and data["started"] == "2026-11-24T10:00:00.000Z"
    assert data["agent"] == "mock" and (data["mock_agent_min_delay_s"], data["mock_agent_max_delay_s"]) == (0.5, 2.0)
    assert data["region"] == "eu-west-1" and data["tiers"] is None and data["memory_mb"] == 512
    assert data["ak_version"]
    assert data["host"] == run_info.host  # a host setting can't replace a harness field

    RunMetadataWriter().write(tmp_path, run_info, at(0), deployment, None)
    data = json.loads((tmp_path / "run-metadata.json").read_text())
    assert data["agent"] == "real" and data["mock_agent_min_delay_s"] is None


def test_step_metadata(tmp_path, config, host, run_info, record):
    host.fetchers.during_step[0].poll_interval_s = 2
    StepMetadataWriter().write(tmp_path, config, host, run_info, record)

    data = json.loads((tmp_path / "step-metadata.json").read_text())
    assert (data["test_type"], data["step"], data["seed"]) == ("steady", 1, 42)
    assert data["max_cooldown_s"] == 600  # host override
    assert data["poll_intervals_s"] == {"scaling": 2, "transport": 5, "trace": 5, "resource": 5, "resource2": 5}
    assert data["percentile_method"] == "linear" and data["time_window_s"] == 10
    assert data["t_load_down"] == "2026-11-24T10:00:40.000Z"


def test_step_folder_padding(tmp_path):
    layout = ResultsLayout(tmp_path, "run")
    assert layout.step_dir("aws", "h", "async", "complete", "steady", 1, [1, 10, 100, 1000]).name == "step-0001"
    assert layout.step_dir("aws", "h", "async", "complete", "steady", 7, [1, 7]).name == "step-7"
