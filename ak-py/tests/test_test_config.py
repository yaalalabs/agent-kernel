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
    assert cfg.judge.model == "gpt-4o-mini"
    assert cfg.judge.provider == "openai"
    assert cfg.judge.embedding_model == "text-embedding-3-small"

    # A missing test-config.yaml is the normal case: no warning is printed
    assert "Could not open yaml settings file" not in capsys.readouterr().out


def test_yaml_loading(tmp_path, monkeypatch):
    cfg_path = tmp_path / "test-config.yaml"
    cfg_path.write_text("mode: judge\njudge:\n  model: gpt-4o\n  provider: azure\n")
    monkeypatch.setenv("AK_TEST_CONFIG_PATH_OVERRIDE", str(cfg_path))

    cfg = AKTestConfig.get()
    assert cfg.mode == "judge"
    assert cfg.judge.model == "gpt-4o"
    assert cfg.judge.provider == "azure"
    # Values not present in the file keep their defaults
    assert cfg.judge.embedding_model == "text-embedding-3-small"


def test_env_overrides(tmp_path, monkeypatch):
    cfg_path = tmp_path / "test-config.yaml"
    cfg_path.write_text("mode: fuzzy\njudge:\n  model: from-file\n")
    monkeypatch.setenv("AK_TEST_CONFIG_PATH_OVERRIDE", str(cfg_path))

    # Env vars keep their pre-split names and override file values
    monkeypatch.setenv("AK_TEST__MODE", "judge")
    monkeypatch.setenv("AK_TEST__JUDGE__MODEL", "from-env")
    monkeypatch.setenv("AK_TEST__JUDGE__PROVIDER", "anthropic")
    monkeypatch.setenv("AK_TEST__JUDGE__EMBEDDING_MODEL", "embed-env")

    cfg = AKTestConfig.get()
    assert cfg.mode == "judge"
    assert cfg.judge.model == "from-env"
    assert cfg.judge.provider == "anthropic"
    assert cfg.judge.embedding_model == "embed-env"


def test_lazy_singleton(monkeypatch):
    cfg_1 = AKTestConfig.get()
    cfg_2 = AKTestConfig.get()
    assert cfg_1 is cfg_2

    monkeypatch.setenv("AK_TEST__MODE", "fuzzy")
    # Cached instance does not see the new env until reset
    assert AKTestConfig.get().mode == "fallback"
    AKTestConfig._reset()
    assert AKTestConfig.get().mode == "fuzzy"


def test_invalid_mode_raises(monkeypatch):
    monkeypatch.setenv("AK_TEST__MODE", "invalid-mode")
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
    app_cfg_path.write_text("test:\n  mode: fuzzy\n")
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(app_cfg_path))

    # test-config.yaml does not affect AKConfig
    test_cfg_path = tmp_path / "test-config.yaml"
    test_cfg_path.write_text("mode: judge\n")
    monkeypatch.setenv("AK_TEST_CONFIG_PATH_OVERRIDE", str(test_cfg_path))

    app_cfg = AKConfig()
    assert not hasattr(app_cfg, "test")

    cfg = AKTestConfig.get()
    assert cfg.mode == "judge"
