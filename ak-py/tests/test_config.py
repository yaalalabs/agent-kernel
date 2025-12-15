import pytest

from agentkernel.core.config import AKConfig


def test_config_defaults_no_file(monkeypatch):
    # Ensure no env interference
    monkeypatch.delenv("AK_DEBUG", raising=False)
    monkeypatch.delenv("AK_SESSION_TYPE", raising=False)

    cfg = AKConfig.get()
    cfg.__init__()  # Reload
    assert cfg.debug is False
    assert cfg.session.type == "in_memory"

    # Defaults for nested redis should be None
    assert cfg.session.redis is None


@pytest.mark.usefixtures("tmp_path")
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

    monkeypatch.setenv("AK_SESSION__TYPE", "in_memory")
    monkeypatch.setenv("AK_SESSION__REDIS__TTL", "999")

    # Lets point to the file we created and reload
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))
    cfg_1 = AKConfig.get()  # instance object which has no yaml file loaded or env settings
    cfg_2 = AKConfig()  # object which loads yaml file and env settings

    # defaults from cfg_1
    assert cfg_1.debug is False
    assert cfg_1.session.type == "in_memory"
    assert cfg_1.session.redis is None

    # File value
    assert cfg_2.debug is True

    # file values overridden by env
    assert cfg_2.session.type == "in_memory"
    assert cfg_2.session.redis is not None
    assert cfg_2.session.redis.ttl == 999

    # File-provided values preserved where env not set
    assert cfg_2.session.redis.url == "redis://example:6379"
    assert cfg_2.session.redis.prefix == "ak:test:"

    # Reload and check default object again
    cfg_1.__init__()
    # File value
    assert cfg_1.debug is True

    # File values overridden by env
    assert cfg_1.session.type == "in_memory"
    assert cfg_1.session.redis is not None
    assert cfg_1.session.redis.ttl == 999

    # File-provided values preserved where env not set
    assert cfg_1.session.redis.url == "redis://example:6379"
    assert cfg_1.session.redis.prefix == "ak:test:"


def test_nested_env_cases(monkeypatch):
    # Set weird env that should not break or set anything

    cfg = AKConfig()
    # All values should remain defaults
    assert cfg.debug is False
    assert cfg.session.type == "in_memory"
    assert cfg.session.redis is None
    assert cfg.api.custom_router_prefix == "/custom"
    assert cfg.a2a.task_store_type == "in_memory"
    assert cfg.mcp.expose_agents is False
    assert cfg.api.enabled_routes.agents is True

    # -------------------------------------------------

    monkeypatch.setenv("AK_SESSION__TYPE", "redis")  # default is in-memory
    monkeypatch.setenv("AK_SESSION__REDIS__TTL", "1000")
    # should be ignored as no double underscore for SESSION module separator. Hence will be taken as 'session_redis_ttl' which does not exist
    monkeypatch.setenv("AK_SESSION_REDIS_TTL", "999")

    # should be ignored SESSION module has no key REDIS_XXX
    monkeypatch.setenv("AK_SESSION__REDIS_XXX", "999")

    monkeypatch.setenv("AK_API__CUSTOM_ROUTER_PREFIX", "/health")  # Should be valid
    monkeypatch.setenv("AK_A2A__TASK_STORE_TYPE", "redis")  # Should be valid
    monkeypatch.setenv("AK_MCP__EXPOSE_AGENTS", "true")  # Should be valid

    monkeypatch.setenv("AK_API__CUSTOM__ROUTER_PREFIX", "/incorrect")  # Should be ignored. No submodule custom in api
    monkeypatch.setenv("AK_API_CUSTOM_ROUTER_PREFIX", "/health")  # Should be ignored

    monkeypatch.setenv("AK_API__ENABLED_ROUTES__AGENTS", "false")  # Default is true. Should be valid

    cfg = AKConfig()
    assert cfg.debug is False  # Should remain default
    assert cfg.session.type == "redis"
    assert cfg.session.redis is not None
    assert cfg.session.redis.ttl == 1000  # from double underscore env
    assert cfg.api.custom_router_prefix == "/health"
    assert cfg.a2a.task_store_type == "redis"
    assert cfg.mcp.expose_agents is True
    assert cfg.api.enabled_routes.agents is False


def test_session_cache_default():
    cfg = AKConfig()
    assert cfg.session is not None
    assert cfg.session.cache is None


def test_session_cache_env(monkeypatch):
    monkeypatch.setenv("AK_SESSION__CACHE__SIZE", "500")
    cfg = AKConfig()
    assert cfg.session is not None
    assert cfg.session.cache is not None
    assert cfg.session.cache.size == 500
