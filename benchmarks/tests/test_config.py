from pathlib import Path

import pytest
import yaml

from ak_bench.config import BenchConfig, MockAgentConfig
from ak_bench.errors import BenchConfigError

EXAMPLE = Path(__file__).resolve().parent.parent / "ak-bench.example.yaml"
REQUIRED = {"step_run": {"time_window_s": 1}, "fetchers": {"default": {"poll_interval_s": 5}}}


def write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "ak-bench.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def test_defaults_equal_786_example(tmp_path):
    config = BenchConfig.load(write(tmp_path, REQUIRED))
    example = yaml.safe_load(EXAMPLE.read_text())

    assert config.hosts is None and config.modes is None and config.message_types is None and config.mock_agent is None
    assert config.test_types == example["test_types"]
    assert config.load_steps == example["load_steps"]
    assert config.step_run.model_dump() == example["step_run"]
    assert config.steady_traffic.model_dump() == example["steady_traffic"]
    assert config.host_settings == {}


def test_example_file_loads():
    config = BenchConfig.load(EXAMPLE)
    assert config.hosts == ["ecs", "lambda"]
    assert config.mock_agent.delays() == (1, 5)


@pytest.mark.parametrize(
    "data, key",
    [
        ({"fetchers": REQUIRED["fetchers"], "step_run": {}}, "step_run.time_window_s"),
        ({"step_run": REQUIRED["step_run"], "fetchers": {"sqs": {"poll_interval_s": 5}}}, "fetchers.default.poll_interval_s"),
        ({"step_run": REQUIRED["step_run"], "fetchers": {"default": {}}}, "fetchers.default.poll_interval_s"),
        ({"step_run": REQUIRED["step_run"]}, "fetchers"),
    ],
)
def test_missing_required_key_is_named(tmp_path, data, key):
    with pytest.raises(BenchConfigError, match=key.replace(".", r"\.")):
        BenchConfig.load(write(tmp_path, data))


def test_unknown_key_is_named(tmp_path):
    data = {**REQUIRED, "step_run": {"time_window_s": 1, "befor_window_s": 2}}
    with pytest.raises(BenchConfigError, match=r"step_run\.befor_window_s"):
        BenchConfig.load(write(tmp_path, data))


@pytest.mark.parametrize(
    "extra",
    [
        {"load_steps": []},
        {"load_steps": [0]},
        {"load_steps": [1, 1]},
        {"steady_traffic": {"min_send_interval_s": 5, "max_send_interval_s": 1}},
        {"steady_traffic": {"min_send_interval_s": 0}},
        {"steady_traffic": {"load_time_s": 0}},
        {"test_types": ["spike"]},
    ],
)
def test_invalid_values_refused(tmp_path, extra):
    with pytest.raises(BenchConfigError):
        BenchConfig.load(write(tmp_path, {**REQUIRED, **extra}))


def test_missing_and_invalid_files(tmp_path):
    with pytest.raises(BenchConfigError, match="not found"):
        BenchConfig.load(tmp_path / "nope.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("step_run: [")
    with pytest.raises(BenchConfigError, match="invalid YAML"):
        BenchConfig.load(bad)
    with pytest.raises(BenchConfigError, match="can't read"):
        BenchConfig.load(tmp_path)


def test_host_settings_accept_any_key_and_override_max_cooldown():
    config = BenchConfig.model_validate({**REQUIRED, "host_settings": {"lambda": {"anything": "x", "max_cooldown_s": 60}, "ecs": {"other": 1}}})
    assert config.host_settings["lambda"].model_extra == {"anything": "x"}
    assert config.max_cooldown_for("lambda") == 60
    assert config.max_cooldown_for("ecs") == 2700
    assert config.max_cooldown_for("unknown") == 2700


def test_poll_interval_for():
    config = BenchConfig.model_validate({**REQUIRED, "fetchers": {"default": {"poll_interval_s": 5}, "sqs": {"poll_interval_s": 2}}})
    assert config.fetchers.poll_interval_for("sqs") == 2
    assert config.fetchers.poll_interval_for("aws.ecs_api") == 5


def test_check_names_refuses_unknown_name_listing_known():
    config = BenchConfig.model_validate({**REQUIRED, "fetchers": {"default": {"poll_interval_s": 5}, "aws.ecs-api": {"poll_interval_s": 5}}})
    with pytest.raises(BenchConfigError, match=r"fetchers\.aws\.ecs-api: .*known: aws\.ecs_api, sqs"):
        config.fetchers.check_names({"sqs", "aws.ecs_api"})
    config.fetchers.check_names({"aws.ecs-api"})


@pytest.mark.parametrize(
    "block, result",
    [
        ({"min_delay": 1, "max_delay": 5}, (1, 5)),
        ({"min_delay": 2, "max_delay": 2}, (2, 2)),
        ({}, None),
    ],
)
def test_mock_agent_delays(block, result):
    assert MockAgentConfig(**block).delays() == result


@pytest.mark.parametrize(
    "block, key",
    [
        ({"min_delay": 1}, "mock_agent.max_delay is missing"),
        ({"max_delay": 1}, "mock_agent.min_delay is missing"),
        ({"min_delay": -1, "max_delay": 1}, "mock_agent.min_delay must not be negative"),
        ({"min_delay": 0, "max_delay": -1}, "mock_agent.max_delay must not be negative"),
        ({"min_delay": 5, "max_delay": 1}, "mock_agent.min_delay .* greater"),
    ],
)
def test_mock_agent_refusals(block, key):
    with pytest.raises(BenchConfigError, match=key):
        MockAgentConfig(**block).delays()


def test_mock_agent_half_set_loads(tmp_path):
    # A half-set block is a deploy refusal, not a load error: step / plot / post-run must still load the file.
    config = BenchConfig.load(write(tmp_path, {**REQUIRED, "mock_agent": {"min_delay": 1}}))
    assert config.mock_agent.min_delay == 1


def test_fast_config(fast_config):
    assert fast_config.step_run.time_window_s == 0.1
    assert fast_config.fetchers.poll_interval_for("x") == 0.05
