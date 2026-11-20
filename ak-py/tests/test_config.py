import subprocess
import sys

import pytest
from pydantic import ValidationError

from agentkernel.core.config import (
    AKConfig,
    _A2AConfig,
    _AGUIConfig,
    _AuthorizationConfig,
    _ExecutionConfig,
    _GrantConfig,
    _IdentityConfig,
    _IdentityProviderConfig,
    _MCPConfig,
    _RegistryAgentOverlayConfig,
    _RegistryConfig,
    _RegistryDynamoDBConfig,
    _RegistryRedisConfig,
    _RegistryValkeyConfig,
    _ScheduleConfig,
    _SecretConfig,
    _StaticProviderConfig,
    _ThreadStoreConfig,
    _ThreadValkeyConfig,
    _ToolPolicyConfig,
)
from agentkernel.core.model import AccessLevel, ExecutionMode, ReplyMessageType
from agentkernel.core.util.factory import AKConfigError


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


def test_batch_size_env_override(tmp_path, monkeypatch):
    """A deployment tunes the declared block through env vars; the type stays the config's."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("execution:\n" "  queues:\n" "    type: sqs\n")
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))
    monkeypatch.setenv("AK_EXECUTION__QUEUES__BATCH_SIZE", "5")
    cfg = AKConfig()
    assert cfg.execution.queues.type == "sqs"
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


def test_schedule_block_absent_by_default(monkeypatch):
    # Absence of the block is the capability-disabled signal, so it must never default to a value.
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")

    assert AKConfig.get().schedule is None


def test_schedule_defaults_make_a_bare_block_usable():
    # A bare 'schedule:' block must work for local development without naming any backend.
    cfg = _ScheduleConfig()
    assert cfg.provider.type == "local"
    assert cfg.store.type == "in_memory"
    assert cfg.agents is None
    # Backend sub-blocks stay opt-in, and schedules never expire by default.
    assert cfg.provider.eventbridge is None
    assert cfg.store.dynamodb is None


def test_schedule_from_yaml(tmp_path, monkeypatch):
    yaml_text = (
        "schedule:\n"
        "  provider:\n"
        "    type: eventbridge\n"
        "    eventbridge:\n"
        "      group_name: ak-schedules\n"
        "      role_arn: arn:aws:iam::123456789012:role/ak-scheduler\n"
        "      queue_arn: arn:aws:sqs:us-east-1:123456789012:ak-input.fifo\n"
        "  store:\n"
        "    type: dynamodb\n"
        "    dynamodb:\n"
        "      table_name: ak-schedules\n"
        "  agents:\n"
        "    - planner\n"
    )
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml_text)
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))
    AKConfig._reset()

    schedule = AKConfig.get().schedule
    assert schedule is not None
    assert schedule.provider.type == "eventbridge"
    assert schedule.provider.eventbridge.group_name == "ak-schedules"
    assert schedule.provider.eventbridge.queue_arn == "arn:aws:sqs:us-east-1:123456789012:ak-input.fifo"
    assert schedule.store.type == "dynamodb"
    assert schedule.store.dynamodb.table_name == "ak-schedules"
    assert schedule.store.dynamodb.ttl == 0
    assert schedule.agents == ["planner"]


def test_schedule_env_var_materializes_the_block(monkeypatch):
    # Same behavior threads have: any AK_SCHEDULE__* variable enables the capability with
    # defaults for everything it does not name.
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    monkeypatch.setenv("AK_SCHEDULE__STORE__TYPE", "redis")

    schedule = AKConfig.get().schedule
    assert schedule is not None
    assert schedule.store.type == "redis"
    assert schedule.provider.type == "local"


def test_secret_defaults(monkeypatch):
    # The block is always present and zero-configuration: the env provider with a 5-minute cache.
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")

    secret = AKConfig.get().secret
    assert secret.prefix == ""
    assert secret.provider.type == "env"
    assert secret.cache_ttl == 300
    assert secret.provider.kubernetes.mount_path == "/var/run/secrets/agentkernel"
    # Resolution order is fixed, so there is no manager selector.
    assert "type" not in _SecretConfig.model_fields


def test_secret_env_vars(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    monkeypatch.setenv("AK_SECRET__PREFIX", "myproduct-dev-agents")
    monkeypatch.setenv("AK_SECRET__PROVIDER__TYPE", "aws_ssm")
    monkeypatch.setenv("AK_SECRET__CACHE_TTL", "0")
    monkeypatch.setenv("AK_SECRET__PROVIDER__KUBERNETES__MOUNT_PATH", "/run/secrets")

    secret = AKConfig.get().secret
    assert secret.prefix == "myproduct-dev-agents"
    assert secret.provider.type == "aws_ssm"
    assert secret.cache_ttl == 0
    assert secret.provider.kubernetes.mount_path == "/run/secrets"


def test_secret_kubernetes_empty_mount_path_keeps_default(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    monkeypatch.setenv("AK_SECRET__PROVIDER__KUBERNETES__MOUNT_PATH", "")

    assert AKConfig.get().secret.provider.kubernetes.mount_path == "/var/run/secrets/agentkernel"


def test_secret_negative_cache_ttl_rejected(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    monkeypatch.setenv("AK_SECRET__CACHE_TTL", "-1")

    with pytest.raises(ValidationError):
        AKConfig.get()


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


def test_queues_transport_defaults(monkeypatch):
    """No queues block at all still runs: the single-process transport is the default topology."""
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    cfg = AKConfig.get()
    assert cfg.execution.queues.type == "in_memory"
    assert cfg.execution.queues.in_memory is None


def test_declared_queues_block_requires_a_transport_type(tmp_path, monkeypatch):
    """The transport is declared, never inferred: a block without a type is a config error."""
    yaml_text = "execution:\n" "  queues:\n" "    input:\n" "      url: https://sqs.test/input\n"
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml_text)
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))

    AKConfig._reset()
    with pytest.raises(ValidationError, match="execution.queues.type"):
        AKConfig.get()


def test_queues_transport_yaml_and_env(tmp_path, monkeypatch):
    yaml_text = "execution:\n" "  queues:\n" "    type: in_memory\n" "    in_memory:\n" "      ack_wait: 1.5\n" "      dedup_window: 60\n"
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml_text)
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))

    AKConfig._reset()
    cfg = AKConfig.get()
    assert cfg.execution.queues.type == "in_memory"
    assert cfg.execution.queues.in_memory.ack_wait == 1.5
    assert cfg.execution.queues.in_memory.dedup_window == 60

    # Env var override uses the AK_ double-underscore nesting for the new field
    monkeypatch.setenv("AK_EXECUTION__QUEUES__TYPE", "kafka")
    AKConfig._reset()
    assert AKConfig.get().execution.queues.type == "kafka"


def test_pubsub_block_absent_by_default(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    assert AKConfig.get().execution.queues.pubsub is None


def test_pubsub_block_defaults_and_yaml(tmp_path, monkeypatch):
    yaml_text = "execution:\n" "  queues:\n" "    type: pubsub\n" "    pubsub:\n" "      project_id: my-project\n" "      auto_provision: true\n"
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml_text)
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))

    pubsub = AKConfig.get().execution.queues.pubsub

    assert AKConfig.get().execution.queues.type == "pubsub"
    assert (pubsub.project_id, pubsub.auto_provision) == ("my-project", True)
    assert (pubsub.input_topic, pubsub.input_subscription) == ("agent-input", "agent-input")
    assert (pubsub.output_topic, pubsub.output_subscription) == ("agent-output", "agent-output")
    assert (pubsub.dlq_suffix, pubsub.ack_wait, pubsub.request_timeout) == ("-dlq", 300.0, 10.0)


def test_pubsub_block_from_env_beside_a_declared_type(tmp_path, monkeypatch):
    """Terraform injects only coordinates; the application's config.yaml declares the type (#886)."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("execution:\n  queues:\n    type: pubsub\n")
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))
    monkeypatch.setenv("AK_EXECUTION__QUEUES__PUBSUB__PROJECT_ID", "env-project")
    monkeypatch.setenv("AK_EXECUTION__QUEUES__PUBSUB__INPUT_TOPIC", "prod-agent-input")
    monkeypatch.setenv("AK_EXECUTION__QUEUES__PUBSUB__DLQ_SUFFIX", "-dead")

    pubsub = AKConfig.get().execution.queues.pubsub

    assert (pubsub.project_id, pubsub.input_topic, pubsub.dlq_suffix) == ("env-project", "prod-agent-input", "-dead")


def test_injected_pubsub_coordinates_without_a_declared_type_fail_at_load(monkeypatch):
    """A deployment cannot pick the transport for the application: the type stays mandatory."""
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    monkeypatch.setenv("AK_EXECUTION__QUEUES__PUBSUB__INPUT_TOPIC", "prod-agent-input")

    with pytest.raises(ValidationError, match="execution.queues.type"):
        AKConfig.get()


def test_servicebus_queue_block_yaml_and_env(tmp_path, monkeypatch):
    yaml_text = "execution:\n" "  queues:\n" "    type: servicebus\n" "    servicebus:\n" "      ack_wait: 120\n"
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml_text)
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))

    cfg = AKConfig.get()
    assert cfg.execution.queues.type == "servicebus"
    assert cfg.execution.queues.servicebus.ack_wait == 120
    assert cfg.execution.queues.servicebus.connection_string is None

    monkeypatch.setenv("AK_EXECUTION__QUEUES__SERVICEBUS__ACK_WAIT", "30")
    monkeypatch.setenv("AK_EXECUTION__QUEUES__SERVICEBUS__CONNECTION_STRING", "Endpoint=sb://localhost/;UseDevelopmentEmulator=true")
    AKConfig._reset()
    servicebus = AKConfig.get().execution.queues.servicebus
    assert servicebus.ack_wait == 30
    assert servicebus.connection_string == "Endpoint=sb://localhost/;UseDevelopmentEmulator=true"


def test_queues_block_without_servicebus_leaves_it_unset(tmp_path, monkeypatch):
    """Old YAML loads unchanged: the servicebus block is optional."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("execution:\n  queues:\n    type: sqs\n")
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))

    assert AKConfig.get().execution.queues.servicebus is None


def test_response_store_accepts_in_memory_type(tmp_path, monkeypatch):
    yaml_text = "execution:\n" "  response_store:\n" "    type: in_memory\n"
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml_text)
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))

    AKConfig._reset()
    cfg = AKConfig.get()
    assert cfg.execution.response_store.type == "in_memory"


def test_response_store_accepts_dotted_path_type():
    """The type field takes built-in short names or a BYO dotted path (#541 factory pattern);
    unknown short names fail loudly at store-build time (see test_response_store_in_memory)."""
    from agentkernel.core.config import _ResponseStoreConfig

    assert _ResponseStoreConfig(type="my_pkg.stores.MyResponseStore").type == "my_pkg.stores.MyResponseStore"


def test_every_messaging_platform_accepts_an_outbound_adapter_override():
    """#524: the outbound half is resolved by name, so bring-your-own goes through config."""
    config = AKConfig()
    for platform in ("slack", "whatsapp", "messenger", "instagram", "telegram", "teams", "gmail"):
        assert getattr(config, platform).outbound_adapter == "", platform


def test_the_outbound_adapter_override_binds_from_the_environment(monkeypatch):
    monkeypatch.setenv("AK_SLACK__OUTBOUND_ADAPTER", "my_pkg.adapters.MySlackOutbound")

    assert AKConfig().slack.outbound_adapter == "my_pkg.adapters.MySlackOutbound"


class TestA2UIConfig:
    """The capability's two keys, and the defaults that keep it inert."""

    def test_defaults_to_disabled_for_every_agent(self, monkeypatch):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        AKConfig._reset()

        config = AKConfig.get()

        assert config.a2ui.enabled is False
        assert config.a2ui.agents is None

    def test_reads_the_env_vars(self, monkeypatch):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        monkeypatch.setenv("AK_A2UI__ENABLED", "true")
        monkeypatch.setenv("AK_A2UI__AGENTS", '["expenses"]')
        AKConfig._reset()

        config = AKConfig.get()

        assert config.a2ui.enabled is True
        assert config.a2ui.agents == ["expenses"]


_MODES = [None, "rest_sync", "rest_async", "async", "realtime"]
_REJECTED_PAIRS = {("rest_async", "delta"), ("realtime", "complete")}


class TestExecutionMessageType:
    @pytest.mark.parametrize("mode", _MODES)
    @pytest.mark.parametrize("message_type", [None, "complete", "delta"])
    def test_mode_message_type_matrix(self, mode, message_type):
        data = {k: v for k, v in (("mode", mode), ("message_type", message_type)) if v is not None}
        if (mode, message_type) in _REJECTED_PAIRS:
            with pytest.raises(AKConfigError) as exc:
                _ExecutionConfig(**data)
            assert "execution.mode" in str(exc.value)
            assert "execution.message_type" in str(exc.value)
        else:
            _ExecutionConfig(**data)

    @pytest.mark.parametrize(
        "mode, expected",
        [
            (None, ReplyMessageType.COMPLETE),
            ("rest_sync", ReplyMessageType.COMPLETE),
            ("rest_async", ReplyMessageType.COMPLETE),
            ("async", ReplyMessageType.COMPLETE),
            ("realtime", ReplyMessageType.DELTA),
        ],
    )
    def test_resolved_message_type_default(self, mode, expected):
        config = _ExecutionConfig(mode=mode)
        assert config.message_type is None
        assert config.resolved_message_type == expected

    @pytest.mark.parametrize(
        "mode, message_type, is_websocket, is_delta, is_sse",
        [
            (None, None, False, False, False),
            (None, "delta", False, True, True),
            ("rest_sync", "complete", False, False, False),
            ("rest_sync", "delta", False, True, True),
            ("rest_async", "complete", False, False, False),
            ("async", "complete", True, False, False),
            ("async", "delta", True, True, False),
            ("realtime", None, False, False, False),
            ("realtime", "delta", False, False, False),
        ],
    )
    def test_predicates(self, mode, message_type, is_websocket, is_delta, is_sse):
        config = _ExecutionConfig(mode=mode, message_type=message_type)
        assert config.is_websocket is is_websocket
        assert config.is_delta is is_delta
        assert config.is_sse is is_sse

    def test_rejected_pair_from_yaml_raises_ak_config_error(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("execution:\n  mode: rest_async\n  message_type: delta\n")
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))
        with pytest.raises(AKConfigError):
            AKConfig.get()

    def test_env_vars_load_async_delta(self, monkeypatch):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        monkeypatch.setenv("AK_EXECUTION__MODE", "async")
        monkeypatch.setenv("AK_EXECUTION__MESSAGE_TYPE", "delta")
        execution = AKConfig.get().execution
        assert execution.mode == ExecutionMode.ASYNC
        assert execution.message_type == ReplyMessageType.DELTA
        assert execution.is_websocket and execution.is_delta

    @staticmethod
    def _assert_stream_migration(exc_info):
        assert exc_info.type is AKConfigError
        message = str(exc_info.value)
        assert message == _ExecutionConfig.STREAM_MIGRATION_MESSAGE
        assert "execution.mode: rest_sync and execution.message_type: delta" in message
        assert "execution.mode: async and execution.message_type: delta" in message

    def test_stream_mode_from_yaml_raises_migration_error(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("execution:\n  mode: stream\n")
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))
        with pytest.raises(AKConfigError) as exc:
            AKConfig.get()
        self._assert_stream_migration(exc)

    def test_stream_mode_from_env_raises_migration_error(self, monkeypatch):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        monkeypatch.setenv("AK_EXECUTION__MODE", "stream")
        with pytest.raises(AKConfigError) as exc:
            AKConfig.get()
        self._assert_stream_migration(exc)

    def test_uppercase_stream_fails_as_unknown_mode(self):
        with pytest.raises(ValidationError):
            _ExecutionConfig(mode="STREAM")

    def test_execution_mode_has_no_stream_member(self):
        assert "stream" not in {m.value for m in ExecutionMode}


class TestIdentityConfig:
    """The `identity` block (#603): absent by default, present means configured, and a block that cannot
    authenticate anyone fails at load time rather than on the first request."""

    def test_absent_by_default(self, monkeypatch):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        assert AKConfig.get().identity is None

    def test_a_static_block_parses_from_yaml(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(
            "identity:\n"
            "  provider:\n"
            "    type: static\n"
            "    static:\n"
            "      principals:\n"
            "        ALICE_TOKEN:\n"
            "          subject: alice\n"
            "          groups: [ops]\n"
            "  role_mapper:\n"
            "    mapping:\n"
            "      ops: [operator]\n"
        )
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))

        identity = AKConfig.get().identity

        assert identity is not None and identity.provider.type == "static"
        assert identity.provider.static.principals["ALICE_TOKEN"].groups == ["ops"]
        assert identity.provider.static.principals["ALICE_TOKEN"].kind == "user"
        assert identity.role_mapper.type == "mapping" and identity.role_mapper.mapping == {"ops": ["operator"]}

    def test_the_default_provider_is_oidc_and_needs_issuer_and_audience(self):
        assert _IdentityProviderConfig(issuer="https://issuer.example", audience="ak").type == "oidc"
        with pytest.raises(AKConfigError, match="identity.provider.issuer and identity.provider.audience"):
            _IdentityConfig()

    @pytest.mark.parametrize("name", ["cognito", "entra", "firebase", "static"])
    def test_a_named_provider_needs_its_block(self, name):
        with pytest.raises(AKConfigError, match=f"identity.provider.{name}"):
            _IdentityProviderConfig(type=name)

    def test_a_dotted_provider_validates_its_own_settings(self):
        assert _IdentityProviderConfig(type="my.module.Provider").type == "my.module.Provider"

    def test_a_static_block_without_principals_still_parses(self):
        """An empty map parses; StaticIdentityProvider refuses it at construction (test_identity_providers)."""
        assert _IdentityProviderConfig(type="static", static=_StaticProviderConfig()).static.principals == {}

    def test_an_identity_env_var_materializes_the_block_and_fails_fast(self, monkeypatch):
        """Any AK_IDENTITY__* variable creates the block; the default oidc type without an issuer is the intended startup failure."""
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        monkeypatch.setenv("AK_IDENTITY__PROVIDER__LEEWAY", "10")
        with pytest.raises(AKConfigError, match="identity.provider.issuer"):
            AKConfig.get()

    def test_claim_paths_and_algorithms_default(self):
        provider = _IdentityProviderConfig(issuer="https://issuer.example", audience="ak")
        assert (provider.claims.subject, provider.claims.groups) == ("sub", "groups")
        assert (provider.algorithms, provider.leeway, provider.required_claims) == (["RS256", "ES256"], 30, [])


class TestRegistryConfig:
    """The `registry` block (#603): absent by default (an in-memory registry), a backend selector with its
    connection block, and the per-agent overlay of deployment-owned catalog fields."""

    def test_absent_by_default(self, monkeypatch):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        assert AKConfig.get().registry is None

    def test_a_block_parses_from_yaml_with_its_backend_and_overlay(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(
            "registry:\n"
            "  type: redis\n"
            "  redis:\n"
            "    url: redis://cache:6379\n"
            "  agents:\n"
            "    support-triage:\n"
            "      version: 1.2.0\n"
            "      description: Triage support tickets\n"
            "      owner: cx-platform\n"
            "      tags: [support]\n"
            "      visibility: internal\n"
            "      surfaces: [rest, agui]\n"
            "      identity:\n"
            "        subject: svc-triage\n"
        )
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))

        registry = AKConfig.get().registry

        assert (registry.type, registry.redis.url) == ("redis", "redis://cache:6379")
        overlay = registry.agents["support-triage"]
        assert (overlay.version, overlay.description, overlay.owner) == ("1.2.0", "Triage support tickets", "cx-platform")
        assert (overlay.tags, overlay.visibility, overlay.surfaces) == (["support"], "internal", ["rest", "agui"])
        assert overlay.identity.subject == "svc-triage"

    def test_a_bare_block_is_the_in_memory_registry_with_no_overlay(self):
        registry = _RegistryConfig()

        assert registry.type == "in_memory"
        assert (registry.redis, registry.valkey, registry.dynamodb) == (None, None, None)
        assert registry.agents == {}

    def test_the_store_blocks_default_to_the_registry_prefix_and_table_and_never_expire(self):
        # Unlike the session defaults these inherit from: a descriptor that expired would drop a running agent from the catalog.
        assert (_RegistryRedisConfig().prefix, _RegistryRedisConfig().ttl) == ("ak:registry:", 0)
        assert (_RegistryValkeyConfig().prefix, _RegistryValkeyConfig().ttl) == ("ak:registry:", 0)
        assert (_RegistryDynamoDBConfig().table_name, _RegistryDynamoDBConfig().ttl) == ("ak-agent-registry", 0)

    @pytest.mark.parametrize(
        "block, model", [("redis", _RegistryRedisConfig), ("valkey", _RegistryValkeyConfig), ("dynamodb", _RegistryDynamoDBConfig)]
    )
    def test_a_store_block_refuses_a_ttl(self, block, model):
        # Nothing registers a hosted agent again while its process runs, so an expiry would remove running agents
        # from every listing. Refused at load rather than accepted and left to do that.
        with pytest.raises(AKConfigError, match=f"registry.{block}.ttl is not supported"):
            model.model_validate({"ttl": 3600})

        assert model.model_validate({"ttl": 0}).ttl == 0

    def test_a_ttl_set_through_the_environment_fails_at_load(self, monkeypatch):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        monkeypatch.setenv("AK_REGISTRY__TYPE", "redis")
        monkeypatch.setenv("AK_REGISTRY__REDIS__TTL", "600")

        with pytest.raises(AKConfigError, match="registry.redis.ttl is not supported"):
            AKConfig.get()

    def test_a_key_the_registry_block_does_not_take_is_rejected(self):
        # `agent:` for `agents:` would otherwise drop every per-agent restriction beneath it without a word.
        with pytest.raises(ValueError, match="agent"):
            _RegistryConfig.model_validate({"agent": {"billing": {"surfaces": []}}})

    def test_a_misspelt_registry_key_in_the_environment_fails_at_load(self, monkeypatch):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        monkeypatch.setenv("AK_REGISTRY__AGENT__BILLING__SURFACES", "[]")

        with pytest.raises(ValueError, match="registry"):
            AKConfig.get()

    def test_an_overlay_entry_sets_nothing_by_default(self):
        assert _RegistryAgentOverlayConfig().model_dump(exclude_none=True) == {}

    def test_an_overlay_key_the_descriptor_does_not_take_is_rejected(self):
        # A misspelt `surfaces` silently ignored would leave an agent on every surface.
        with pytest.raises(ValueError, match="surface"):
            _RegistryAgentOverlayConfig.model_validate({"surface": ["rest"]})

    @pytest.mark.parametrize("field, value", [("visibility", "secret"), ("surfaces", ["grpc"])])
    def test_an_overlay_value_outside_the_descriptors_choices_is_rejected(self, field, value):
        with pytest.raises(ValueError, match=field):
            _RegistryAgentOverlayConfig.model_validate({field: value})

    def test_a_registry_env_var_materializes_the_block(self, monkeypatch):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        monkeypatch.setenv("AK_REGISTRY__TYPE", "valkey")

        assert AKConfig.get().registry.type == "valkey"


class TestAuthorizationConfig:
    """The `authorization` block (#603): absent by default (nothing is restricted), and when present the static
    backend's policy: grants binding subjects to agents at a level, and a per-agent tool policy."""

    def test_absent_by_default(self, monkeypatch):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        assert AKConfig.get().authorization is None

    def test_a_block_parses_from_yaml_with_its_grants_and_tool_policies(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(
            "authorization:\n"
            "  type: static\n"
            "  grants:\n"
            '    - {subjects: role:admin, agents: "*", level: admin}\n'
            "    - {subjects: [group:support, role:cx-lead], agents: [support-triage, faq], level: write}\n"
            "    - {subjects: authenticated, agents: tag:support, level: read}\n"
            "  tools:\n"
            "    - agent: support-triage\n"
            "      tiers: {lookup_ticket: read, create_ticket: write, refund: admin}\n"
            "      allow: [lookup_ticket, create_ticket, refund]\n"
            "      deny: [delete_ticket]\n"
        )
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))

        authorization = AKConfig.get().authorization

        assert authorization.type == "static"
        assert [(grant.subjects, grant.agents, grant.level) for grant in authorization.grants] == [
            (["role:admin"], ["*"], AccessLevel.ADMIN),
            (["group:support", "role:cx-lead"], ["support-triage", "faq"], AccessLevel.WRITE),
            (["authenticated"], ["tag:support"], AccessLevel.READ),
        ]
        [policy] = authorization.tools
        assert policy.agent == "support-triage"
        assert policy.tiers == {"lookup_ticket": AccessLevel.READ, "create_ticket": AccessLevel.WRITE, "refund": AccessLevel.ADMIN}
        assert (policy.allow, policy.deny) == (["lookup_ticket", "create_ticket", "refund"], ["delete_ticket"])

    def test_a_bare_block_is_the_static_backend_with_no_policy(self):
        authorization = _AuthorizationConfig()

        assert (authorization.type, authorization.grants, authorization.tools) == ("static", [], [])

    def test_a_grant_takes_one_subject_or_agent_as_a_bare_string(self):
        grant = _GrantConfig.model_validate({"subjects": "group:support", "agents": "faq", "level": "read"})

        assert (grant.subjects, grant.agents) == (["group:support"], ["faq"])

    def test_a_grant_level_outside_the_three_tiers_is_rejected(self):
        with pytest.raises(ValueError, match="level"):
            _GrantConfig.model_validate({"subjects": "*", "agents": "faq", "level": "owner"})

    def test_a_grant_key_the_model_does_not_take_is_rejected(self):
        # `agent:` for `agents:` must fail where it is written, not leave a grant that names no agent.
        with pytest.raises(ValueError, match="agent"):
            _GrantConfig.model_validate({"subjects": "*", "agent": "faq", "agents": "faq", "level": "read"})

    def test_a_tool_policy_restricts_nothing_until_it_says_so(self):
        policy = _ToolPolicyConfig(agent="support-triage")

        # No allow-list (None) is every tool; an empty one would be none of them.
        assert (policy.tiers, policy.allow, policy.deny) == ({}, None, [])

    def test_a_tool_policy_key_the_model_does_not_take_is_rejected(self):
        # A misspelt `deny` silently ignored would leave the tool callable.
        with pytest.raises(ValueError, match="denied"):
            _ToolPolicyConfig.model_validate({"agent": "support-triage", "denied": ["delete_ticket"]})

    def test_a_tool_tier_outside_the_three_tiers_is_rejected(self):
        with pytest.raises(ValueError, match="tiers"):
            _ToolPolicyConfig.model_validate({"agent": "support-triage", "tiers": {"refund": "owner"}})

    @pytest.mark.parametrize("key", ["tool", "grant"])
    def test_a_misspelt_block_key_is_rejected_for_the_static_backend(self, key):
        # `tool:` for `tools:` would otherwise drop every tier and deny list beneath it without a word.
        with pytest.raises(AKConfigError, match=f"authorization.{key}"):
            _AuthorizationConfig.model_validate({"type": "static", key: []})

    def test_a_bring_your_own_authorizer_keeps_the_settings_of_its_own(self):
        authorization = _AuthorizationConfig.model_validate({"type": "acme.authz.PolicyServer", "endpoint": "https://pdp.acme.test"})

        assert authorization.model_extra == {"endpoint": "https://pdp.acme.test"}

    def test_an_authorization_env_var_materializes_the_block(self, monkeypatch):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        monkeypatch.setenv("AK_AUTHORIZATION__TYPE", "static")

        authorization = AKConfig.get().authorization

        # Present with no grants: every agent is then denied, which is what the static backend warns about.
        assert (authorization.type, authorization.grants) == ("static", [])

    def test_grants_set_through_the_environment_are_parsed(self, monkeypatch):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        monkeypatch.setenv("AK_AUTHORIZATION__GRANTS", '[{"subjects": "*", "agents": ["faq"], "level": "read"}]')

        [grant] = AKConfig.get().authorization.grants

        assert (grant.subjects, grant.agents, grant.level) == (["*"], ["faq"], AccessLevel.READ)


class TestRemovedAgentLists:
    """`a2a.agents`, `mcp.agents` and `agui.agents` are gone (#603): an agent's surfaces are part of its
    descriptor. A configuration that still sets one fails at load with where the setting went, rather than
    being ignored and leaving every agent on the surface."""

    @pytest.mark.parametrize("block, model", [("a2a", _A2AConfig), ("mcp", _MCPConfig), ("agui", _AGUIConfig)])
    def test_a_block_that_still_lists_agents_fails_with_the_migration_message(self, block, model):
        with pytest.raises(AKConfigError, match=f"{block}.agents was removed: set registry.agents.<id>.surfaces instead"):
            model.model_validate({"agents": ["triage"]})

    @pytest.mark.parametrize("block, model", [("a2a", _A2AConfig), ("mcp", _MCPConfig), ("agui", _AGUIConfig)])
    def test_the_blocks_no_longer_carry_an_agents_field(self, block, model):
        assert "agents" not in model.model_fields

    def test_a_yaml_file_that_still_sets_one_fails_at_load(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("mcp:\n  enabled: true\n  agents: ['*']\n")
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))

        with pytest.raises(AKConfigError, match="mcp.agents was removed"):
            AKConfig.get()

    def test_an_environment_variable_that_still_sets_one_fails_at_load(self, monkeypatch):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        monkeypatch.setenv("AK_A2A__AGENTS", '["triage"]')

        with pytest.raises(AKConfigError, match="a2a.agents was removed"):
            AKConfig.get()

    def test_the_tool_scoping_lists_under_agui_are_untouched(self):
        agui = _AGUIConfig.model_validate({"state": {"enabled": True, "agents": ["a"]}, "client_context": {"agents": ["b"]}})

        assert (agui.state.agents, agui.client_context.agents) == (["a"], ["b"])
