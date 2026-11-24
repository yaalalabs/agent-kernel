from ak_bench.platforms.base import Fetchers, Host
from mocks.fetchers import MockCostFetcher, MockResourceFetcher, MockScalingFetcher, MockTraceCollector, MockTransportCollector


def mock_host() -> Host:
    """A Host built from fresh mock fetchers; scaling and transport are the same objects in both lists."""
    scaling = MockScalingFetcher("scaling")
    transport = MockTransportCollector("transport")
    return Host(
        platform="mock",
        fetchers=Fetchers(
            during_step=[scaling, transport],
            cooldown_checks=[transport, scaling],
            after_step=[MockTraceCollector("trace"), MockResourceFetcher("resource")],
            after_all_steps=[],
            after_teardown=[MockCostFetcher("cost")],
        ),
    )
