import pytest

from ak.core.config import AKConfig


def test_config_defaults_no_file(tmp_path, monkeypatch):
    # Ensure no env interference
    monkeypatch.delenv("AK_DEBUG", raising=False)
    monkeypatch.delenv("AK_SESSION_TYPE", raising=False)
    # Use a non-existent file path
    cfg = AKConfig._load(str(tmp_path / "missing.yaml"))
    assert cfg.debug is False
    assert cfg.session.type == "in_memory"
    # Defaults for nested redis
    assert cfg.session.redis.url.startswith("redis://")
    assert cfg.session.redis.ttl > 0


def test_config_yaml_and_env_override(tmp_path, monkeypatch):
    # Write YAML file
    yaml_text = (
        "debug: true\n"
        "session:\n"
        "  type: redis\n"
        "  redis:\n"
        "    url: redis://example:6379\n"
        "    ttl: 120\n"
        "    prefix: 'ak:test:'\n"
    )
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml_text)

    # Environment should override nested value, and env_prefix AK_ with nested delimiter _
    monkeypatch.setenv("AK_SESSION_TYPE", "in_memory")
    monkeypatch.setenv("AK_SESSION_REDIS_TTL", "999")

    cfg = AKConfig._load(str(cfg_path))

    # File value
    assert cfg.debug is True
    # Overridden by env
    assert cfg.session.type == "in_memory"
    assert cfg.session.redis.ttl == 999
    # File-provided values preserved where env not set
    assert cfg.session.redis.url == "redis://example:6379"
    assert cfg.session.redis.prefix == "ak:test:"


@pytest.mark.parametrize(
    "env_key,env_val,expect",
    [
        ("AK_", "", None),  # empty key should be ignored
        ("AK__", "value", None),  # double delimiter leading to empty parts ignored
    ],
)
def test_env_ignored_edge_cases(tmp_path, monkeypatch, env_key, env_val, expect):
    # Base file values
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("debug: false\n")

    # Set weird env that should not break or set anything
    monkeypatch.setenv(env_key, env_val)

    cfg = AKConfig._load(str(cfg_path))
    # Should remain default as in file
    assert cfg.debug is False
