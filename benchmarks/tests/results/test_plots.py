from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import numpy
import pytest
from mocks.fetchers import MockCostFetcher
from test_results import at, config, deployment, host, record, step_dir  # noqa: F401  (fixtures shared with the CSV tests)

from ak_bench.fetchers.core.cost import CostInfo, CostItem
from ak_bench.load.driver.ws_complete import WebSocketCompleteDriver
from ak_bench.results.csv.per_request import PerRequestWriter
from ak_bench.results.csv.per_window import PerWindowWriter
from ak_bench.results.graphs.cost_graph import CostReport
from ak_bench.results.graphs.plots import Plots
from ak_bench.results.graphs.step_graphs import StepPlots
from ak_bench.results.metadata import StepMetadataWriter
from ak_bench.run.run_log import RunLog

STEP_GRAPHS = ["01-stage-times.png", "02-stage-breakdown.png", "03-timeline.png", "04-every-request.png", "05-resource-usage.png"]


@pytest.fixture
def run_log(tmp_path) -> RunLog:
    return RunLog(tmp_path / "run.log", "plot")


def errors(run_log: RunLog) -> list[str]:
    return [line for line in run_log.path.read_text().splitlines() if " ERROR " in line] if run_log.path.exists() else []


def write_step_csvs(step_dir: Path, record, config, host, deployment, run_info) -> None:  # noqa: F811
    """What `step` writes before it plots: the step CSVs and step-metadata.json."""
    PerRequestWriter(WebSocketCompleteDriver).write(step_dir, record.load.records)
    PerWindowWriter(config, host, deployment).write(step_dir, record)
    StepMetadataWriter().write(step_dir, config, host, run_info, record)


def test_every_steady_graph_from_recorded_data(step_dir, record, config, host, deployment, run_info, run_log):  # noqa: F811
    write_step_csvs(step_dir, record, config, host, deployment, run_info)

    StepPlots(run_log).draw(step_dir, "steady", host, deployment)

    assert sorted(p.name for p in (step_dir / "graphs").iterdir()) == STEP_GRAPHS
    assert not (step_dir.parent / "graphs").exists()  # no graphs comparing the steps (#786 Later)
    assert errors(run_log) == []


def test_burst_with_all_empty_resource_data_still_draws_every_panel(step_dir, record, config, host, deployment, run_info, run_log):  # noqa: F811
    (step_dir / "resource-usage.csv").unlink()
    record = replace(record, test_type="burst")
    write_step_csvs(step_dir, record, config, host, deployment, run_info)
    second = step_dir.parent / "step-2"
    second.mkdir()  # a step with no data at all

    StepPlots(run_log).draw(step_dir, "burst", host, deployment)
    StepPlots(run_log).draw(second, "burst", host, deployment)

    expected = [g for g in STEP_GRAPHS if g != "04-every-request.png"]  # steady only
    assert sorted(p.name for p in (step_dir / "graphs").iterdir()) == expected
    assert sorted(p.name for p in (second / "graphs").iterdir()) == expected
    assert errors(run_log) == []


def test_every_request_bands_group_requests_by_send_window():
    windows = [{"window_start": "2026-11-24T10:00:00.000Z"}, {"window_start": "2026-11-24T10:00:01.000Z"}]
    row = lambda sent, latency, status="ok": {"sent": sent, "latency_s": latency, "status": status}
    requests = [
        row("2026-11-24T10:00:00.900Z", "0.5"),  # completes in window 1, but was sent in window 0
        row("2026-11-24T10:00:01.000Z", "0.2"),  # on the boundary: window 1
        row("2026-11-24T10:00:01.100Z", "", "timeout"),  # drawn on the timeout line, not in the bands
    ]

    p = StepPlots.by_send_window(windows, requests)

    assert list(p["p50"]) == [0.5, 0.2] and list(p["p100"]) == [0.5, 0.2]
    assert numpy.isnan(StepPlots.by_send_window(windows, [])["p50"]).all()


def test_a_failing_graph_is_logged_and_the_others_still_draw(step_dir, record, config, host, deployment, run_info, run_log, monkeypatch):  # noqa: F811
    write_step_csvs(step_dir, record, config, host, deployment, run_info)

    def broken(*_):
        raise ValueError("bad data")

    monkeypatch.setattr(StepPlots, "_stage_breakdown", broken)
    StepPlots(run_log).draw(step_dir, "steady", host, deployment)

    assert sorted(p.name for p in (step_dir / "graphs").iterdir()) == [g for g in STEP_GRAPHS if g != "02-stage-breakdown.png"]  # and no .tmp left
    [line] = errors(run_log)
    assert "02-stage-breakdown.png" in line and "ValueError: bad data" in line and "kept" not in line

    # a redraw that fails leaves the previous graph in place and says so
    monkeypatch.undo()
    StepPlots(run_log).draw(step_dir, "steady", host, deployment)
    before = (step_dir / "graphs" / "02-stage-breakdown.png").read_bytes()
    monkeypatch.setattr(StepPlots, "_stage_breakdown", broken)
    StepPlots(run_log).draw(step_dir, "steady", host, deployment)
    assert (step_dir / "graphs" / "02-stage-breakdown.png").read_bytes() == before
    assert errors(run_log)[-1].endswith("the previous graph is kept and is out of date")


@pytest.mark.parametrize(
    "values, labels",
    [
        ([0.2, 0.5], ["200 ms", "300 ms", "400 ms", "500 ms"]),  # inside one decade: every digit, never unlabelled
        ([0.21, 0.52, 30], ["200 ms", "500 ms", "1 s", "2 s", "5 s", "10 s", "20 s"]),  # wider: 1, 2, 5 per decade
    ],
)
def test_seconds_axis_labels_every_range(values, labels):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    ax.plot(range(len(values)), values)
    Plots.seconds_axis(ax)
    fig.canvas.draw()
    lo, hi = ax.get_ylim()
    try:
        assert [t.get_text() for t, v in zip(ax.get_yticklabels(), ax.get_yticks(), strict=True) if lo <= v <= hi] == labels
        t_lo, t_top, t_hi = ax.yaxis.get_transform().transform([lo, max(values), hi])
        assert (t_hi - t_top) / (t_hi - t_lo) > 0.04  # headroom measured in symlog space: the top value is off the edge
    finally:
        plt.close(fig)


def test_cost_graph_only_when_cost_csv_exists(tmp_path, run_log):
    CostReport(run_log).draw(tmp_path)
    assert not (tmp_path / "graphs").exists()

    day = datetime(2026, 11, 24, tzinfo=UTC)
    items = [CostItem(day, at(86400), "AmazonECS", 1.25, "UnblendedCost"), CostItem(day, at(86400), "AWSLambda", 0.1, "UnblendedCost")]
    MockCostFetcher("cost").store(CostInfo(items), tmp_path)
    CostReport(run_log).draw(tmp_path)

    assert (tmp_path / "graphs" / "cost-by-service.png").stat().st_size > 0
    assert errors(run_log) == []
