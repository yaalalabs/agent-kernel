import pytest
from bench_config import BenchAppConfig
from pydantic import ValidationError

MIN, MAX = "AK_BENCH_MOCK_AGENT_MIN_DELAY_S", "AK_BENCH_MOCK_AGENT_MAX_DELAY_S"


@pytest.fixture(autouse=True)
def fresh_config(monkeypatch, tmp_path):
    monkeypatch.setenv("AK_BENCH_CONFIG_PATH_OVERRIDE", str(tmp_path / "bench-config.yaml"))
    monkeypatch.delenv(MIN, raising=False)
    monkeypatch.delenv(MAX, raising=False)
    BenchAppConfig._reset()
    yield
    BenchAppConfig._reset()


def test_env_vars_give_mock_delays(monkeypatch):
    monkeypatch.setenv(MIN, "0.5")
    monkeypatch.setenv(MAX, "1.5")
    assert BenchAppConfig.get().mock_delays == (0.5, 1.5)


def test_neither_set_means_real_agent():
    assert BenchAppConfig.get().mock_delays is None


def test_empty_values_count_as_unset(monkeypatch):
    monkeypatch.setenv(MIN, "")
    monkeypatch.setenv(MAX, "")
    assert BenchAppConfig.get().mock_delays is None


def test_yaml_file_is_read_and_env_wins(monkeypatch, tmp_path):
    (tmp_path / "bench-config.yaml").write_text("mock_agent_min_delay_s: 1\nmock_agent_max_delay_s: 2\n")
    assert BenchAppConfig.get().mock_delays == (1, 2)
    BenchAppConfig._reset()
    monkeypatch.setenv(MAX, "3")
    assert BenchAppConfig.get().mock_delays == (1, 3)


def test_get_is_a_singleton():
    assert BenchAppConfig.get() is BenchAppConfig.get()


@pytest.mark.parametrize(
    "low, high, message",
    [("1", None, "set both"), (None, "1", "set both"), ("-1", "1", "greater than or equal to 0"), ("2", "1", "greater than")],
)
def test_bad_delays_refused(monkeypatch, low, high, message):
    for name, value in ((MIN, low), (MAX, high)):
        if value is not None:
            monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError, match=message):
        BenchAppConfig.get()
