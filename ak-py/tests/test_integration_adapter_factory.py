"""IntegrationAdapterFactory: how an `integration` attribute value becomes an outbound adapter."""

import sys
import types
from typing import Any, Dict

import pytest

from agentkernel.core.config import AKConfig
from agentkernel.core.model import AgentReply
from agentkernel.core.util.factory import AKConfigError
from agentkernel.integration.adapter.base import InboundAdapter, InboundParseResult, OutboundAdapter, Source
from agentkernel.integration.adapter.factory import IntegrationAdapterFactory


class RecordingOutboundAdapter(OutboundAdapter):
    """A bring-your-own outbound adapter, resolved by dotted path."""

    name = "recording"
    MESSAGE_LIMIT = 10

    def __init__(self):
        self.delivered: list = []
        self.errors: list = []

    async def deliver(self, reply: AgentReply, reply_context: Dict[str, str]) -> None:
        self.delivered.append((str(reply), reply_context))

    async def deliver_error(self, message: str, reply_context: Dict[str, str]) -> None:
        self.errors.append((message, reply_context))


class NotAnAdapter:
    """Resolvable by dotted path, but not an OutboundAdapter."""


class MinimalInboundAdapter(InboundAdapter):
    name = "recording"
    source = Source.WEBHOOK
    webhook_path = "/recording/webhook"

    async def parse(self, raw: Any) -> InboundParseResult:
        return InboundParseResult()


BYO = "byo_pkg.RecordingOutboundAdapter"


@pytest.fixture(autouse=True)
def _byo_module(monkeypatch):
    """Make resolve_dotted's importlib resolve `byo_pkg` to this module's classes."""
    import agentkernel.core.util.factory as factory_module

    namespace = types.SimpleNamespace(
        RecordingOutboundAdapter=RecordingOutboundAdapter,
        NotAnAdapter=NotAnAdapter,
        MinimalInboundAdapter=MinimalInboundAdapter,
    )
    real = factory_module.importlib.import_module
    monkeypatch.setattr(
        factory_module.importlib,
        "import_module",
        lambda name, *a, **k: namespace if name == "byo_pkg" else real(name, *a, **k),
    )
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    AKConfig._reset()
    IntegrationAdapterFactory.reset()
    yield
    AKConfig._reset()
    IntegrationAdapterFactory.reset()


def test_a_dotted_path_resolves_to_a_bring_your_own_adapter():
    assert isinstance(IntegrationAdapterFactory.create_outbound(BYO), RecordingOutboundAdapter)


def test_a_platform_config_override_replaces_the_built_in(monkeypatch):
    monkeypatch.setenv("AK_SLACK__OUTBOUND_ADAPTER", BYO)
    AKConfig._reset()
    # Resolves without importing slack_bolt: the override short-circuits the built-in branch.
    assert isinstance(IntegrationAdapterFactory.create_outbound("slack"), RecordingOutboundAdapter)


def test_every_platform_block_accepts_an_override(monkeypatch):
    for name in IntegrationAdapterFactory._BUILTIN_NAMES:
        monkeypatch.setenv(f"AK_{name.upper()}__OUTBOUND_ADAPTER", BYO)
        AKConfig._reset()
        IntegrationAdapterFactory.reset()
        assert isinstance(IntegrationAdapterFactory.create_outbound(name), RecordingOutboundAdapter), name


def test_an_unknown_bare_name_is_a_configuration_error():
    with pytest.raises(AKConfigError) as excinfo:
        IntegrationAdapterFactory.create_outbound("carrier-pigeon")
    message = str(excinfo.value)
    assert "carrier-pigeon" in message
    assert "slack" in message, "the error should name the built-ins the caller could have meant"


def test_a_dotted_path_to_the_wrong_type_is_a_configuration_error():
    with pytest.raises(AKConfigError):
        IntegrationAdapterFactory.create_outbound("byo_pkg.NotAnAdapter")


def test_an_unimportable_dotted_path_is_a_configuration_error():
    with pytest.raises(AKConfigError):
        IntegrationAdapterFactory.create_outbound("agentkernel.no_such_module_xyz.Thing")


def test_the_same_name_resolves_to_one_shared_instance():
    # The Response Handler resolves per output message across several consumer threads; adapters
    # own SDK clients, so a second instance per message would be a leak.
    assert IntegrationAdapterFactory.create_outbound(BYO) is IntegrationAdapterFactory.create_outbound(BYO)


def test_reset_drops_the_cache():
    first = IntegrationAdapterFactory.create_outbound(BYO)
    IntegrationAdapterFactory.reset()
    assert IntegrationAdapterFactory.create_outbound(BYO) is not first


def test_an_inbound_adapter_is_never_resolved_by_name():
    # Only the outbound half crosses the queue as a string; inbound adapters are constructed by
    # the application. Resolving one by dotted path must fail on the base-class check.
    with pytest.raises(AKConfigError):
        IntegrationAdapterFactory.create_outbound("byo_pkg.MinimalInboundAdapter")


def test_a_missing_built_in_dependency_names_its_extra(monkeypatch):
    # A None entry in sys.modules makes `from ... import ...` raise ImportError, which is what a
    # missing optional SDK looks like from the factory's side.
    monkeypatch.setitem(sys.modules, "agentkernel.integration.slack.adapter", None)
    with pytest.raises(ImportError) as excinfo:
        IntegrationAdapterFactory.create_outbound("slack")
    assert "agentkernel[slack]" in str(excinfo.value)
    assert "integration 'slack'" in str(excinfo.value)
