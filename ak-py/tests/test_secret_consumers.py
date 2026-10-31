"""Framework-owned credentials resolve through ``SecretManager`` (#858).

Every consumer is held to the same three behaviours: a set environment variable wins without the
provider being asked (for an ``AKConfig`` field the variable is the field's own ``AK_*`` name, so
the configured value wins); with it unset the provider's entry is used; and a provider failure
surfaces as ``SecretError`` instead of passing for a missing credential.

``TestNoDirectCredentialReads`` keeps it that way: no framework module may read a credential
straight from ``os.environ``.
"""

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pytest

from agentkernel.core.config import AKConfig
from agentkernel.secret import SecretError, SecretManager, SecretProvider

ENV_VALUE = "from-env"
PROVIDER_VALUE = "from-provider"
SIBLING_VALUE = "sibling"


class _DictSecretProvider(SecretProvider):
    """Answers from a dict and records every key it is asked for."""

    def __init__(self, values: Dict[str, str]) -> None:
        self._values = values
        self.calls: List[str] = []

    def get_secret(self, key):
        self.calls.append(key)
        return self._values.get(key)


class _FailingSecretProvider(SecretProvider):
    def get_secret(self, key):
        raise SecretError(f"backend failed for '{key}'")


# --- How each consumer exposes the value it resolved -------------------------------------------


def _walledai(monkeypatch) -> str:
    pytest.importorskip("walledai")
    from agentkernel.guardrail import walledai

    seen = {}
    monkeypatch.setattr(walledai, "WalledRedact", lambda api_key: seen.setdefault("api_key", api_key))
    monkeypatch.setattr(walledai, "WalledProtect", lambda api_key: None)
    walledai.WalledAIGuardrailBase()
    return seen["api_key"]


def _slack_inbound_token(monkeypatch) -> str:
    pytest.importorskip("slack_bolt")
    from agentkernel.integration.slack.adapter import SlackInboundAdapter

    return SlackInboundAdapter()._app.client.token


def _slack_inbound_signing_secret(monkeypatch) -> str:
    pytest.importorskip("slack_bolt")
    from agentkernel.integration.slack.adapter import SlackInboundAdapter

    return SlackInboundAdapter()._app._signing_secret


def _slack_outbound_token(monkeypatch) -> str:
    pytest.importorskip("slack_bolt")
    from agentkernel.integration.slack.adapter import SlackOutboundAdapter

    return SlackOutboundAdapter._client().token


def _gmail(attribute: str) -> Callable:
    def resolve(monkeypatch) -> str:
        pytest.importorskip("google_auth_oauthlib")
        from agentkernel.integration.gmail.adapter import _GmailService

        return getattr(_GmailService(), attribute)

    return resolve


def _neo4j(monkeypatch) -> str:
    pytest.importorskip("neo4j")
    from agentkernel.knowledgebase import neo4j

    class _Driver:
        def verify_connectivity(self):
            pass

    seen = {}

    class _GraphDatabase:
        @staticmethod
        def driver(uri, auth=None):
            seen["auth"] = auth
            return _Driver()

    monkeypatch.setattr(neo4j, "GraphDatabase", _GraphDatabase)
    neo4j.Neo4jManager(uri="bolt://fake:7687", user="neo4j")
    return seen["auth"][1]


def _starburst(monkeypatch) -> str:
    pytest.importorskip("trino")
    from agentkernel.knowledgebase.starburst import StarburstManager

    seen = {}
    monkeypatch.setattr("trino.dbapi.connect", lambda **kwargs: object())
    monkeypatch.setattr("trino.auth.BasicAuthentication", lambda user, password: seen.setdefault("password", password))
    StarburstManager(host="fake.galaxy", user="u", catalog="c", schema="s", table_name="t")
    return seen["password"]


def _e2b(monkeypatch) -> str:
    pytest.importorskip("e2b_code_interpreter")
    from agentkernel.core.config import _SandboxE2BConfig
    from agentkernel.sandbox.providers.e2b import E2BSandboxProvider

    return E2BSandboxProvider(_SandboxE2BConfig())._api_key()


def _daytona(monkeypatch) -> str:
    pytest.importorskip("daytona")
    from agentkernel.core.config import _SandboxDaytonaConfig
    from agentkernel.sandbox.providers import daytona

    monkeypatch.setattr(daytona, "DaytonaConfig", lambda api_key, target: api_key)
    monkeypatch.setattr(daytona, "Daytona", lambda config: config)
    return daytona.DaytonaSandboxProvider(_SandboxDaytonaConfig())._client()


def _whatsapp(attribute: str) -> Callable:
    def resolve(monkeypatch) -> str:
        from agentkernel.integration.whatsapp.adapter import _WhatsAppClient

        return getattr(_WhatsAppClient(), attribute)

    return resolve


def _meta_inbound(platform: str, attribute: str) -> Callable:
    def resolve(monkeypatch) -> str:
        if platform == "messenger":
            from agentkernel.integration.messenger.adapter import MessengerInboundAdapter as adapter_cls
        else:
            from agentkernel.integration.instagram.adapter import InstagramInboundAdapter as adapter_cls

        adapter = adapter_cls()
        return adapter._api._access_token if attribute == "access_token" else getattr(adapter, f"_{attribute}")

    return resolve


def _telegram(attribute: str) -> Callable:
    def resolve(monkeypatch) -> str:
        from agentkernel.integration.telegram.adapter import _TelegramClient

        return getattr(_TelegramClient(), attribute)

    return resolve


def _teams(monkeypatch) -> str:
    pytest.importorskip("botbuilder.core")
    from agentkernel.integration.teams.adapter import _TeamsCredentials

    return _TeamsCredentials()._app_password


def _livekit(attribute: str) -> Callable:
    def resolve(monkeypatch) -> str:
        pytest.importorskip("livekit")
        from agentkernel.integration.livekit.adapter import LiveKitEdgeGateway

        return getattr(LiveKitEdgeGateway(agent_name="helper", session_id="room-1"), attribute)

    return resolve


class _ClientBuilt(Exception):
    """Raised by a stand-in SDK client to stop a realtime connect once the key is captured."""


def _realtime_key(monkeypatch, client_path: str, runner_cls, sdk_agent) -> str:
    """Connect a realtime runner just far enough for it to build its SDK client, and return the key it was given."""
    import asyncio
    import types

    from agentkernel.core import Session

    seen = {}

    def client(*args, api_key=None, **kwargs):
        seen["api_key"] = api_key
        raise _ClientBuilt()

    monkeypatch.setattr(client_path, client)

    async def callback(event_type, data):
        pass

    agent = types.SimpleNamespace(name=sdk_agent.name, agent=sdk_agent)
    with pytest.raises(_ClientBuilt):
        asyncio.run(runner_cls().connect(Session("room-1"), agent, callback))
    return seen["api_key"]


def _openai_realtime(monkeypatch) -> str:
    pytest.importorskip("agents")
    from agents import Agent

    from agentkernel.framework.openai.openai import OpenAIRealtimeRunner

    return _realtime_key(monkeypatch, "openai.AsyncOpenAI", OpenAIRealtimeRunner, Agent(name="helper", model="gpt-realtime"))


def _adk_realtime(monkeypatch) -> str:
    pytest.importorskip("google.adk")
    from google.adk.agents import LlmAgent

    from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

    sdk_agent = LlmAgent(name="helper", model="gemini-live-2.5-flash-preview", instruction="Help.")
    return _realtime_key(monkeypatch, "google.genai.Client", GoogleADKRealtimeRunner, sdk_agent)


def _push_auth_token(monkeypatch) -> Optional[str]:
    from agentkernel.pipeline.ws.push import push_auth_token

    return push_auth_token(AKConfig.get())


@dataclass
class Consumer:
    key: str
    resolve: Callable
    # Settings the consumer also needs, set in the environment in every case so that `key` is the
    # only one left for the provider.
    siblings: Dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.key


_WHATSAPP = {"AK_WHATSAPP__ACCESS_TOKEN": SIBLING_VALUE, "AK_WHATSAPP__VERIFY_TOKEN": SIBLING_VALUE, "AK_WHATSAPP__PHONE_NUMBER_ID": "123"}
_MESSENGER = {"AK_MESSENGER__ACCESS_TOKEN": SIBLING_VALUE, "AK_MESSENGER__VERIFY_TOKEN": SIBLING_VALUE, "AK_MESSENGER__APP_SECRET": SIBLING_VALUE}
_INSTAGRAM = {"AK_INSTAGRAM__ACCESS_TOKEN": SIBLING_VALUE, "AK_INSTAGRAM__VERIFY_TOKEN": SIBLING_VALUE, "AK_INSTAGRAM__APP_SECRET": SIBLING_VALUE}
_LIVEKIT = {"AK_LIVEKIT__API_KEY": SIBLING_VALUE, "AK_LIVEKIT__API_SECRET": SIBLING_VALUE}


def _without(siblings: Dict[str, str], key: str) -> Dict[str, str]:
    return {name: value for name, value in siblings.items() if name != key}


CONSUMERS = [
    Consumer("WALLED_API_KEY", _walledai),
    Consumer("SLACK_BOT_TOKEN", _slack_inbound_token, {"SLACK_SIGNING_SECRET": SIBLING_VALUE}),
    Consumer("SLACK_SIGNING_SECRET", _slack_inbound_signing_secret, {"SLACK_BOT_TOKEN": SIBLING_VALUE}),
    Consumer("SLACK_BOT_TOKEN", _slack_outbound_token),
    Consumer("AK_GMAIL__CLIENT_ID", _gmail("_client_id"), {"AK_GMAIL__CLIENT_SECRET": SIBLING_VALUE}),
    Consumer("AK_GMAIL__CLIENT_SECRET", _gmail("_client_secret"), {"AK_GMAIL__CLIENT_ID": SIBLING_VALUE}),
    Consumer("NEO4J_PASSWORD", _neo4j),
    Consumer("STARBURST_PASSWORD", _starburst),
    Consumer("E2B_API_KEY", _e2b),
    Consumer("DAYTONA_API_KEY", _daytona),
    *[
        Consumer(key, _whatsapp(attribute), _without(_WHATSAPP, key))
        for key, attribute in [
            ("AK_WHATSAPP__ACCESS_TOKEN", "_access_token"),
            ("AK_WHATSAPP__VERIFY_TOKEN", "verify_token"),
            ("AK_WHATSAPP__APP_SECRET", "app_secret"),
        ]
    ],
    *[
        Consumer(
            f"AK_{platform.upper()}__{attribute.upper()}",
            _meta_inbound(platform, attribute),
            _without(siblings, f"AK_{platform.upper()}__{attribute.upper()}"),
        )
        for platform, siblings in [("messenger", _MESSENGER), ("instagram", _INSTAGRAM)]
        for attribute in ["access_token", "verify_token", "app_secret"]
    ],
    Consumer("AK_TELEGRAM__BOT_TOKEN", _telegram("_bot_token"), {"AK_TELEGRAM__WEBHOOK_SECRET": SIBLING_VALUE}),
    Consumer("AK_TELEGRAM__WEBHOOK_SECRET", _telegram("webhook_secret"), {"AK_TELEGRAM__BOT_TOKEN": SIBLING_VALUE}),
    Consumer("AK_TEAMS__APP_PASSWORD", _teams, {"AK_TEAMS__APP_ID": "app-id"}),
    Consumer("AK_LIVEKIT__API_KEY", _livekit("_api_key"), _without(_LIVEKIT, "AK_LIVEKIT__API_KEY")),
    Consumer("AK_LIVEKIT__API_SECRET", _livekit("_api_secret"), _without(_LIVEKIT, "AK_LIVEKIT__API_SECRET")),
    Consumer("AK_WEBSOCKET_API__PUSH_AUTH_TOKEN", _push_auth_token),
    Consumer("OPENAI_API_KEY", _openai_realtime),
    Consumer("GOOGLE_API_KEY", _adk_realtime),
]


# Consumers that refuse to start without their credential, so their error must say where to set it.
REQUIRED = [
    consumer
    for consumer in CONSUMERS
    if consumer.key
    in {
        "WALLED_API_KEY",
        "SLACK_SIGNING_SECRET",
        "AK_GMAIL__CLIENT_ID",
        "AK_GMAIL__CLIENT_SECRET",
        "E2B_API_KEY",
        "DAYTONA_API_KEY",
        "AK_WHATSAPP__ACCESS_TOKEN",
        "AK_WHATSAPP__VERIFY_TOKEN",
        "AK_MESSENGER__ACCESS_TOKEN",
        "AK_MESSENGER__VERIFY_TOKEN",
        "AK_INSTAGRAM__ACCESS_TOKEN",
        "AK_INSTAGRAM__VERIFY_TOKEN",
        "AK_TELEGRAM__BOT_TOKEN",
        "AK_TEAMS__APP_PASSWORD",
        "AK_LIVEKIT__API_KEY",
        "AK_LIVEKIT__API_SECRET",
    }
    or consumer.resolve is _slack_inbound_token
]


def _consumer_id(consumer: Consumer) -> str:
    return f"{consumer.resolve.__qualname__.split('.')[0]}-{consumer.key}"


def _isolate(consumer: Consumer, monkeypatch):
    """Isolate the consumer's settings: no config file, its siblings set, its own key unset."""
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    for name in {consumer.key, *consumer.siblings}:
        monkeypatch.delenv(name, raising=False)
    for name, value in consumer.siblings.items():
        monkeypatch.setenv(name, value)
    AKConfig._reset()
    yield consumer
    AKConfig._reset()


@pytest.fixture(params=CONSUMERS, ids=_consumer_id)
def consumer(request, monkeypatch):
    yield from _isolate(request.param, monkeypatch)


@pytest.fixture(params=REQUIRED, ids=_consumer_id)
def required_consumer(request, monkeypatch):
    yield from _isolate(request.param, monkeypatch)


class _LocatedSecretProvider(_DictSecretProvider):
    """An empty provider that names where it looks, the way aws_ssm does."""

    def describe(self, key):
        return f"SSM parameter /ak/test/{key.lower()}"


def _install(monkeypatch, provider: SecretProvider) -> None:
    monkeypatch.setattr(SecretManager, "_instance", SecretManager(provider, cache_ttl=0))


class TestFrameworkConsumers:
    def test_environment_wins_without_asking_the_provider(self, consumer, monkeypatch):
        provider = _DictSecretProvider({consumer.key: PROVIDER_VALUE})
        _install(monkeypatch, provider)
        monkeypatch.setenv(consumer.key, ENV_VALUE)
        AKConfig._reset()

        assert consumer.resolve(monkeypatch) == ENV_VALUE
        assert consumer.key not in provider.calls

    def test_provider_supplies_the_value_when_the_environment_has_none(self, consumer, monkeypatch):
        provider = _DictSecretProvider({consumer.key: PROVIDER_VALUE})
        _install(monkeypatch, provider)

        assert consumer.resolve(monkeypatch) == PROVIDER_VALUE
        assert consumer.key in provider.calls

    def test_provider_failure_raises_secret_error(self, consumer, monkeypatch):
        _install(monkeypatch, _FailingSecretProvider())

        with pytest.raises(SecretError, match=consumer.key):
            consumer.resolve(monkeypatch)

    def test_a_missing_credential_names_where_to_set_it(self, required_consumer, monkeypatch):
        _install(monkeypatch, _LocatedSecretProvider({}))

        with pytest.raises(Exception) as exc_info:
            required_consumer.resolve(monkeypatch)

        message = str(exc_info.value)
        assert f"the {required_consumer.key} environment variable" in message
        assert f"SSM parameter /ak/test/{required_consumer.key.lower()}" in message

    def test_the_push_token_errors_name_where_to_set_it(self, monkeypatch):
        from agentkernel.pipeline.ws.push import push_auth_token_sources

        _install(monkeypatch, _LocatedSecretProvider({}))

        assert push_auth_token_sources() == (
            "websocket_api.push_auth_token, the AK_WEBSOCKET_API__PUSH_AUTH_TOKEN environment variable "
            "or SSM parameter /ak/test/ak_websocket_api__push_auth_token"
        )

    def test_the_webhook_guard_names_where_to_set_a_verification_secret(self, monkeypatch):
        from agentkernel.deployment.aws.serverless.core.webhook_host import LambdaWebhookGuard

        _install(monkeypatch, _LocatedSecretProvider({}))

        assert "SSM parameter /ak/test/ak_whatsapp__app_secret" in LambdaWebhookGuard._sources("whatsapp.app_secret")
        assert LambdaWebhookGuard._sources("a bring-your-own setting") == "a bring-your-own setting"


class TestConfigFieldsResolveLazily:
    def test_loading_akconfig_never_builds_the_secret_manager(self, monkeypatch):
        """SecretManager is built from AKConfig, so resolving while AKConfig loads would recurse."""
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        monkeypatch.setattr(SecretManager, "_instance", None)
        AKConfig._reset()
        try:
            AKConfig.get()
            assert SecretManager._instance is None
        finally:
            AKConfig._reset()

    def test_configured_value_wins_without_asking_the_provider(self, monkeypatch, tmp_path):
        """A value from config.yaml is used as-is; only an empty field falls back."""
        from agentkernel.integration.whatsapp.adapter import _WhatsAppClient

        config_file = tmp_path / "config.yaml"
        config_file.write_text("whatsapp:\n  access_token: from-yaml\n  verify_token: from-yaml\n  app_secret: from-yaml\n  phone_number_id: '123'\n")
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(config_file))
        for name in ("AK_WHATSAPP__ACCESS_TOKEN", "AK_WHATSAPP__VERIFY_TOKEN", "AK_WHATSAPP__APP_SECRET"):
            monkeypatch.delenv(name, raising=False)
        provider = _DictSecretProvider({"AK_WHATSAPP__ACCESS_TOKEN": PROVIDER_VALUE})
        _install(monkeypatch, provider)
        AKConfig._reset()
        try:
            client = _WhatsAppClient()
        finally:
            AKConfig._reset()

        assert client._access_token == "from-yaml"
        assert provider.calls == []


# --- No credential is read straight from os.environ ---------------------------------------------

SRC = Path(__file__).resolve().parents[1] / "src" / "agentkernel"

# A literal key naming a credential. Anything matching must go through SecretManager.
CREDENTIAL_KEY = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL", re.IGNORECASE)

# Literal keys that match CREDENTIAL_KEY but name no credential, each reviewed.
NOT_CREDENTIALS = {
    "AK_SECRETS_PATH",  # the directory pydantic-settings reads secret files from, not a secret
}

# Environment reads whose key is not a literal, each reviewed as not a credential:
# (path under src/agentkernel, the key expression as written).
NON_LITERAL_ALLOWED = {
    ("core/util/config_yaml_util.py", "settings_cls.yaml_file_env_var"),  # config.yaml location
    ("deployment/aws/serverless/core/webhook_host.py", "name"),  # API_BASE_PATH / API_VERSION / AGENT_ENDPOINT
    ("trace/cloudwatch/cloudwatch.py", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"),  # collector URL
    ("trace/cloudwatch/cloudwatch.py", "OTEL_EXPORTER_OTLP_ENDPOINT"),
}


class _EnvironmentReads(ast.NodeVisitor):
    """Collects every os.environ / os.getenv read in one module: (line, key expression, literal key or None)."""

    def __init__(self, module: ast.Module) -> None:
        self._constants = {
            target.id: node.value.value
            for node in module.body
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        self.reads: List[tuple] = []
        self.visit(module)

    @staticmethod
    def _is_environ(node: ast.AST) -> bool:
        return (isinstance(node, ast.Attribute) and node.attr == "environ") or (isinstance(node, ast.Name) and node.id == "environ")

    def _record(self, node: ast.AST, key: ast.AST) -> None:
        literal = key.value if isinstance(key, ast.Constant) and isinstance(key.value, str) else None
        if literal is None and isinstance(key, ast.Name):
            literal = self._constants.get(key.id)
        self.reads.append((node.lineno, ast.unparse(key), literal))

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        is_getenv = (isinstance(func, ast.Attribute) and func.attr == "getenv") or (isinstance(func, ast.Name) and func.id == "getenv")
        is_environ_method = isinstance(func, ast.Attribute) and func.attr in ("get", "setdefault", "pop") and self._is_environ(func.value)
        if (is_getenv or is_environ_method) and node.args:
            self._record(node, node.args[0])
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if self._is_environ(node.value):
            self._record(node, node.slice)
        self.generic_visit(node)


class TestNoDirectCredentialReads:
    def test_no_framework_module_reads_a_credential_from_the_environment(self):
        violations = []
        for path in sorted(SRC.rglob("*.py")):
            relative = path.relative_to(SRC).as_posix()
            if relative.startswith("secret/"):  # the one package that is meant to read the environment
                continue
            for line, expression, literal in _EnvironmentReads(ast.parse(path.read_text(), filename=relative)).reads:
                if literal is None and (relative, expression) not in NON_LITERAL_ALLOWED:
                    violations.append(f"{relative}:{line}: environment read with a computed key `{expression}`")
                elif literal is not None and CREDENTIAL_KEY.search(literal) and literal not in NOT_CREDENTIALS:
                    violations.append(f"{relative}:{line}: credential `{literal}` read from the environment")

        assert not violations, (
            "Resolve credentials through SecretManager.current().get(KEY, ...) instead of os.environ/os.getenv, "
            "so they can come from the configured secret provider:\n" + "\n".join(violations)
        )

    def test_the_scan_catches_a_direct_read(self):
        module = ast.parse(
            "import os\nTOKEN = 'X_TOKEN'\n"
            "a = os.environ.get('SLACK_BOT_TOKEN')\nb = os.getenv(TOKEN)\nc = os.environ['WALLED_API_KEY']\nd = os.environ.get(name)\n"
        )
        assert [(expression, literal) for _, expression, literal in _EnvironmentReads(module).reads] == [
            ("'SLACK_BOT_TOKEN'", "SLACK_BOT_TOKEN"),
            ("TOKEN", "X_TOKEN"),
            ("'WALLED_API_KEY'", "WALLED_API_KEY"),
            ("name", None),
        ]
