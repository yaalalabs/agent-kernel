import pytest
from pydantic import ValidationError

from agentkernel.test.config import AKTestConfig


@pytest.fixture(autouse=True)
def reset_test_config_singleton():
    AKTestConfig._reset()
    yield
    AKTestConfig._reset()


def test_defaults_no_file(capsys, monkeypatch):
    # Point at a nonexistent file so a test-config.yaml in the CWD can't interfere
    monkeypatch.setenv("AK_TEST_CONFIG_PATH_OVERRIDE", "/nonexistent/test-config.yaml")
    cfg = AKTestConfig.get()
    assert cfg.mode == "fallback"
    assert cfg.evaluator == "deepeval"
    assert cfg.llm.model == "gpt-4o-mini"
    assert cfg.llm.provider == "openai"
    assert cfg.llm.embedding_model == "text-embedding-3-small"

    # A missing test-config.yaml is the normal case: no warning is printed
    assert "Could not open yaml settings file" not in capsys.readouterr().out


def test_yaml_loading(tmp_path, monkeypatch):
    cfg_path = tmp_path / "test-config.yaml"
    cfg_path.write_text("mode: llm\nevaluator: deepeval\nllm:\n  model: gpt-4o\n  provider: azure\n")
    monkeypatch.setenv("AK_TEST_CONFIG_PATH_OVERRIDE", str(cfg_path))

    cfg = AKTestConfig.get()
    assert cfg.mode == "llm"
    assert cfg.evaluator == "deepeval"
    assert cfg.llm.model == "gpt-4o"
    assert cfg.llm.provider == "azure"
    # Values not present in the file keep their defaults
    assert cfg.llm.embedding_model == "text-embedding-3-small"


def test_env_overrides(tmp_path, monkeypatch):
    cfg_path = tmp_path / "test-config.yaml"
    cfg_path.write_text("mode: score\nllm:\n  model: from-file\n")
    monkeypatch.setenv("AK_TEST_CONFIG_PATH_OVERRIDE", str(cfg_path))

    # Env vars keep their pre-split names and override file values
    monkeypatch.setenv("AK_TEST__MODE", "llm")
    monkeypatch.setenv("AK_TEST__EVALUATOR", "tests.test_test_config._DummyEvaluator")
    monkeypatch.setenv("AK_TEST__LLM__MODEL", "from-env")
    monkeypatch.setenv("AK_TEST__LLM__PROVIDER", "anthropic")
    monkeypatch.setenv("AK_TEST__LLM__EMBEDDING_MODEL", "embed-env")

    cfg = AKTestConfig.get()
    assert cfg.mode == "llm"
    assert cfg.evaluator == "tests.test_test_config._DummyEvaluator"
    assert cfg.llm.model == "from-env"
    assert cfg.llm.provider == "anthropic"
    assert cfg.llm.embedding_model == "embed-env"


def test_lazy_singleton(monkeypatch):
    cfg_1 = AKTestConfig.get()
    cfg_2 = AKTestConfig.get()
    assert cfg_1 is cfg_2

    monkeypatch.setenv("AK_TEST__MODE", "score")
    # Cached instance does not see the new env until reset
    assert AKTestConfig.get().mode == "fallback"
    AKTestConfig._reset()
    assert AKTestConfig.get().mode == "score"


def test_invalid_mode_raises(monkeypatch):
    monkeypatch.setenv("AK_TEST__MODE", "invalid-mode")
    with pytest.raises(ValidationError):
        AKTestConfig.get()


@pytest.mark.parametrize("legacy_mode", ["fuzzy", "judge"])
def test_legacy_mode_names_rejected(monkeypatch, legacy_mode):
    monkeypatch.setenv("AK_TEST__MODE", legacy_mode)
    with pytest.raises(ValidationError):
        AKTestConfig.get()


def test_missing_override_path_falls_back_to_defaults(monkeypatch):
    monkeypatch.setenv("AK_TEST_CONFIG_PATH_OVERRIDE", "/nonexistent/test-config.yaml")
    cfg = AKTestConfig.get()
    assert cfg.mode == "fallback"


def test_independent_from_akconfig(tmp_path, monkeypatch):
    from agentkernel.core.config import AKConfig

    # A test: section in config.yaml does not affect AKTestConfig and is ignored by AKConfig
    app_cfg_path = tmp_path / "config.yaml"
    app_cfg_path.write_text("test:\n  mode: score\n")
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(app_cfg_path))

    # test-config.yaml does not affect AKConfig
    test_cfg_path = tmp_path / "test-config.yaml"
    test_cfg_path.write_text("mode: llm\n")
    monkeypatch.setenv("AK_TEST_CONFIG_PATH_OVERRIDE", str(test_cfg_path))

    app_cfg = AKConfig()
    assert not hasattr(app_cfg, "test")

    cfg = AKTestConfig.get()
    assert cfg.mode == "llm"


def test_legacy_judge_key_in_yaml_is_silently_ignored(tmp_path, monkeypatch):
    # No special-cased rejection: a leftover `judge:` block is just an unknown key under
    # extra="ignore", and llm keeps its own default rather than reading from `judge:`.
    cfg_path = tmp_path / "test-config.yaml"
    cfg_path.write_text("mode: fallback\njudge:\n  model: gpt-4o\n")
    monkeypatch.setenv("AK_TEST_CONFIG_PATH_OVERRIDE", str(cfg_path))

    cfg = AKTestConfig.get()
    assert cfg.mode == "fallback"
    assert cfg.llm.model == "gpt-4o-mini"
