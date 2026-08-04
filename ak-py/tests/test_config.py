import subprocess
import sys

import pytest

from agentkernel.core.config import AKConfig, _ThreadStoreConfig, _ThreadValkeyConfig


@pytest.fixture(autouse=True)
def reset_config_singleton():
    AKConfig._reset()
    yield
    AKConfig._reset()


def test_config_defaults_no_file(monkeypatch):
    # Ensure no env interference
    monkeypatch.delenv("AK_SESSION_TYPE", raising=False)
    # Point at a nonexistent file so a config.yaml in the CWD can't interfere
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")

    cfg = AKConfig.get()
    assert cfg.session.type == "in_memory"

    # Defaults for nested redis should be None
    assert cfg.session.redis is None


@pytest.mark.usefixtures("tmp_path")
def test_config_yaml_and_env_override(tmp_path, monkeypatch):
    # Write YAML file
    yaml_text = "session:\n" "  type: redis\n" "  redis:\n" "    url: redis://example:6379\n" "    ttl: 120\n" "    prefix: 'ak:test:'\n"
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml_text)

    # Instance created before the yaml file and env overrides are in place gets defaults
    cfg_1 = AKConfig.get()
    assert cfg_1.session.type == "in_memory"
    assert cfg_1.session.redis is None

    # Environment should override nested value, and env_prefix AK_ with nested delimiter _

    monkeypatch.setenv("AK_SESSION__TYPE", "in_memory")
    monkeypatch.setenv("AK_SESSION__REDIS__TTL", "999")

    # Lets point to the file we created and reload
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))
    cfg_2 = AKConfig()  # object which loads yaml file and env settings

    # file values overridden by env
    assert cfg_2.session.type == "in_memory"
    assert cfg_2.session.redis is not None
    assert cfg_2.session.redis.ttl == 999

    # File-provided values preserved where env not set
    assert cfg_2.session.redis.url == "redis://example:6379"
    assert cfg_2.session.redis.prefix == "ak:test:"

    # Reset the singleton and check the reloaded instance picks up yaml + env
    AKConfig._reset()
    cfg_3 = AKConfig.get()

    # File values overridden by env
    assert cfg_3.session.type == "in_memory"
    assert cfg_3.session.redis is not None
    assert cfg_3.session.redis.ttl == 999

    # File-provided values preserved where env not set
    assert cfg_3.session.redis.url == "redis://example:6379"
    assert cfg_3.session.redis.prefix == "ak:test:"


def test_nested_env_cases(monkeypatch):
    # Set weird env that should not break or set anything

    cfg = AKConfig()
    # All values should remain defaults
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
    assert cfg.session.type == "redis"
    assert cfg.session.redis is not None
    assert cfg.session.redis.ttl == 1000  # from double underscore env
    assert cfg.api.custom_router_prefix == "/health"
    assert cfg.a2a.task_store_type == "redis"
    assert cfg.mcp.expose_agents is True
    assert cfg.api.enabled_routes.agents is False


def test_valkey_config_default_none():
    cfg = AKConfig()
    assert cfg.session.valkey is None


def test_valkey_config_yaml_and_env_override(tmp_path, monkeypatch):
    yaml_text = "session:\n" "  type: valkey\n" "  valkey:\n" "    url: valkey://example:6379\n" "    ttl: 120\n" "    prefix: 'ak:test:'\n"
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml_text)

    monkeypatch.setenv("AK_SESSION__TYPE", "valkey")
    monkeypatch.setenv("AK_SESSION__VALKEY__TTL", "999")
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))

    cfg = AKConfig()
    assert cfg.session.type == "valkey"
    assert cfg.session.valkey is not None
    # env overrides file
    assert cfg.session.valkey.ttl == 999
    # file value preserved where env not set
    assert cfg.session.valkey.url == "valkey://example:6379"
    assert cfg.session.valkey.prefix == "ak:test:"


def test_response_store_valkey_config(tmp_path, monkeypatch):
    yaml_text = "execution:\n" "  mode: rest_async\n" "  response_store:\n" "    type: valkey\n" "    valkey:\n" "      url: valkey://example:6379\n"
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml_text)
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))

    cfg = AKConfig()
    assert cfg.execution.response_store.type == "valkey"
    assert cfg.execution.response_store.valkey is not None
    assert cfg.execution.response_store.valkey.url == "valkey://example:6379"
    # prefix default is overridden to the response-store default
    assert cfg.execution.response_store.valkey.prefix == "ak:responses:"


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


def test_batch_size_default():
    cfg = AKConfig()
    assert cfg.execution.queues.batch_size is None


def test_batch_size_env_override(monkeypatch):
    monkeypatch.setenv("AK_EXECUTION__QUEUES__BATCH_SIZE", "5")
    cfg = AKConfig()
    assert cfg.execution.queues.batch_size == 5


def test_guardrail_pii_default():
    cfg = AKConfig()
    assert cfg.guardrail.input.pii is True
    assert cfg.guardrail.output.pii is True


def test_guardrail_pii_env_override(monkeypatch):
    monkeypatch.setenv("AK_GUARDRAIL__INPUT__PII", "false")
    monkeypatch.setenv("AK_GUARDRAIL__OUTPUT__PII", "false")
    cfg = AKConfig()
    assert cfg.guardrail.input.pii is False
    assert cfg.guardrail.output.pii is False


def test_config_has_no_test_section(tmp_path, monkeypatch):
    # The test harness configuration moved to AKTestConfig / test-config.yaml
    assert "test" not in AKConfig.model_fields

    # A legacy config.yaml still carrying a test: section loads without error
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("test:\n  mode: fuzzy\nsession:\n  type: in_memory\n")
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))
    cfg = AKConfig()
    assert cfg.session.type == "in_memory"
    assert not hasattr(cfg, "test")


def test_lazy_singleton_identity():
    cfg_1 = AKConfig.get()
    cfg_2 = AKConfig.get()
    assert cfg_1 is cfg_2

    AKConfig._reset()
    cfg_3 = AKConfig.get()
    assert cfg_3 is not cfg_1


def test_thread_valkey_defaults():
    # _ThreadValkeyConfig narrows _ValkeyConfig for thread use: a 30-day TTL and a
    # thread-scoped key prefix, rather than session's 7-day TTL / "ak:sessions:".
    cfg = _ThreadValkeyConfig()
    assert cfg.url == "valkey://localhost:6379"
    assert cfg.ttl == 2592000
    assert cfg.prefix == "ak:thread:"


def test_thread_valkey_absent_by_default():
    # Every thread backend sub-block is opt-in; the store guards on it being None.
    assert _ThreadStoreConfig().valkey is None


def test_thread_type_valkey_from_yaml(tmp_path, monkeypatch):
    yaml_text = "thread:\n" "  type: valkey\n" "  valkey:\n" "    url: valkey://example:6379\n" "    ttl: 120\n" "    prefix: 'ak:t:'\n"
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml_text)
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))
    AKConfig._reset()

    cfg = AKConfig.get()
    assert cfg.thread.type == "valkey"
    assert cfg.thread.valkey.url == "valkey://example:6379"
    assert cfg.thread.valkey.ttl == 120
    assert cfg.thread.valkey.prefix == "ak:t:"
    # Sibling backends stay unset
    assert cfg.thread.redis is None


def test_import_does_not_load_config(tmp_path):
    # Fresh interpreter so imports are clean; cwd without a config.yaml so the
    # missing-file warning would show up if AKConfig were loaded at import.
    code = (
        "import agentkernel\n"
        "from agentkernel.core.config import AKConfig\n"
        "assert AKConfig._instance is None, 'AKConfig loaded by import agentkernel'\n"
        "from agentkernel.test import Test, AKTestConfig\n"
        "assert AKConfig._instance is None, 'AKConfig loaded by agentkernel.test import'\n"
        "assert AKTestConfig._instance is None, 'AKTestConfig loaded at import'\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "Could not open yaml settings file" not in result.stdout
