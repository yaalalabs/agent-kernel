from datetime import UTC, datetime

import pytest
from mocks.fetchers import MockResourceFetcher, MockScalingFetcher, MockTraceCollector, RaisingFetcher, WrongTypeFetcher

from ak_bench.errors import FetcherTypeError, HostRefused, ScriptFailed
from ak_bench.fetchers.core.stage_fetchers import StageFetchers
from ak_bench.hosts.host import Deployment
from ak_bench.run.fetcher_invoker import FetcherInvoker
from ak_bench.run.run_log import RunLog

T0 = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)
T1 = datetime(2026, 11, 24, 10, 1, tzinfo=UTC)


def test_validate_refuses_cooldown_fetcher_without_is_settled():
    with pytest.raises(HostRefused, match="host 'h'.*'resource'.*is_settled"):
        StageFetchers(cooldown_checks=[MockResourceFetcher("resource")]).validate("h")


def test_validate_refuses_scaling_cooldown_fetcher_without_running():
    scaling = MockScalingFetcher("scaling")
    scaling.count_types = frozenset({"desired"})
    with pytest.raises(HostRefused, match="host 'h'.*'scaling'.*running"):
        StageFetchers(cooldown_checks=[scaling]).validate("h")


def test_validate_refuses_nameless_fetcher():
    with pytest.raises(HostRefused, match="host 'h'.*MockTraceCollector has no name"):
        StageFetchers(after_step=[MockTraceCollector("")]).validate("h")


def test_validate_accepts_scaling_in_cooldown_and_any_fetcher_elsewhere():
    StageFetchers(during_step=[MockResourceFetcher("resource")], cooldown_checks=[MockScalingFetcher("scaling")]).validate("h")


def test_all_returns_distinct_fetchers_in_first_seen_order():
    a, b = MockScalingFetcher("a"), MockTraceCollector("b")
    assert StageFetchers(during_step=[a], cooldown_checks=[a], after_step=[b, a]).all() == [a, b]


def test_fetch_and_store_wrong_type_names_fetcher_and_types(tmp_path, run_info, deployment):
    with pytest.raises(FetcherTypeError, match="fetcher 'wrong': fetch\\(\\) returned ScalingInfo, expected ResourceUsage"):
        WrongTypeFetcher("wrong").fetch_and_store(run_info, deployment, T0, T1, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_deployment_json_round_trip_and_missing_key():
    data = {
        "endpoint": "ws://x",
        "resources": {"api": {"arn": "a"}},
        "queues": {"input": {}, "output": {}},
        "logs": {"api": "g"},
        "settings": {"k": 1},
    }
    assert Deployment.from_json(data).to_json() == data
    with pytest.raises(ScriptFailed, match="queues"):
        Deployment.from_json({k: v for k, v in data.items() if k != "queues"})
    with pytest.raises(ScriptFailed, match="must be a JSON object, got list"):
        Deployment.from_json([])


@pytest.mark.parametrize("fetcher", [RaisingFetcher("broken"), WrongTypeFetcher("broken")])
def test_invoker_logs_failure_and_stores_nothing(tmp_path, run_info, deployment, fetcher):
    log = RunLog(tmp_path / "run.log", "step")
    assert FetcherInvoker(run_info, deployment, log).fetch_and_store(fetcher, "after_step", T0, T1, tmp_path) is False
    assert not (tmp_path / "resource-usage.csv").exists()
    line = (tmp_path / "run.log").read_text()
    assert " ERROR step fetcher broken in after_step failed: " in line


def test_invoker_fetch_returns_result_or_logs(tmp_path, run_info, deployment):
    invoker = FetcherInvoker(run_info, deployment, RunLog(tmp_path / "run.log", "step"))
    ok, result = invoker.fetch(MockScalingFetcher("scaling"), "cooldown_checks", T0, T1)
    assert ok and result.samples == []
    assert invoker.fetch(RaisingFetcher("broken"), "cooldown_checks", T0, T1) == (False, None)
    assert invoker.fetch(WrongTypeFetcher("wrong"), "cooldown_checks", T0, T1) == (False, None)
    assert "fetcher wrong in cooldown_checks failed: FetcherTypeError: " in (tmp_path / "run.log").read_text()
    assert "fetcher broken in cooldown_checks failed: RuntimeError: broken is broken" in (tmp_path / "run.log").read_text()
