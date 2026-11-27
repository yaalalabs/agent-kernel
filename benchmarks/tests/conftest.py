import pytest

from ak_bench.config import BenchConfig
from ak_bench.hosts.host import Deployment, RunInfo


@pytest.fixture
def fast_config() -> BenchConfig:
    """A BenchConfig with every wait scaled down to tenths of a second."""
    return BenchConfig.model_validate(
        {
            "load_steps": [1, 2],
            "step_run": {
                "before_window_s": 0.2,
                "after_step_wait_s": 0.1,
                "cooldown_poll_interval_s": 0.05,
                "time_window_s": 0.1,
                "client_timeout_s": 1,
            },
            "steady_traffic": {"min_send_interval_s": 0.1, "max_send_interval_s": 0.2, "load_time_s": 0.5},
            "fetchers": {"default": {"poll_interval_s": 0.05}},
        }
    )


@pytest.fixture
def run_info() -> RunInfo:
    return RunInfo("20261124T100000Z", "20261124T100000Z-mock-async-complete", "mock", "mock", "async", "complete")


@pytest.fixture
def deployment() -> Deployment:
    return Deployment("ws://127.0.0.1:1", {}, {"input": {}, "output": {}}, {}, {})


@pytest.fixture(autouse=True)
def short_auth_grace(monkeypatch):
    """A refused token is seen within milliseconds on 127.0.0.1; keeps each connect() short."""
    from ak_bench.load.driver.ws_complete import WebSocketCompleteDriver

    monkeypatch.setattr(WebSocketCompleteDriver, "AUTH_GRACE_S", 0.05)
