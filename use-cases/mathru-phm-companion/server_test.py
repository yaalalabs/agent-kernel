"""Exercise the published webhook imports and startup wiring without external services."""

import runpy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from agentkernel.integration.adapter import WebhookRESTRequestHandler
from agentkernel.whatsapp import WhatsAppInboundAdapter


@pytest.fixture
def server_module():
    with patch("agentkernel.openai.OpenAIModule"), patch("redaction.install"), patch("dotenv.load_dotenv"):
        return runpy.run_path(str(Path(__file__).with_name("server.py")))


def test_server_hosts_the_whatsapp_webhook_through_the_pipeline(server_module, monkeypatch):
    config = SimpleNamespace(
        whatsapp=SimpleNamespace(
            agent="mathru_triage",
            access_token="test",
            phone_number_id="test",
            verify_token="test",
            app_secret="test",
            api_version="v24.0",
        ),
        api=SimpleNamespace(max_file_size=1024),
    )
    monkeypatch.setattr(server_module["Config"], "get", lambda: config)
    run = Mock()
    monkeypatch.setattr(server_module["IOHandler"], "run", run)
    # Keep the real webhook handler, but avoid initializing a queue transport in this unit test.
    monkeypatch.setitem(
        server_module["main"].__globals__,
        "WebhookRESTRequestHandler",
        lambda adapter: WebhookRESTRequestHandler(adapter, producer=Mock()),
    )
    server_module["main"]()
    handler = run.call_args.kwargs["handlers"][0]
    assert isinstance(handler, WebhookRESTRequestHandler)
    assert isinstance(handler._adapter, WhatsAppInboundAdapter)
    assert handler.requires_pipeline
    assert {(route.path, tuple(sorted(route.methods))) for route in handler.get_router().routes} == {
        ("/whatsapp/webhook", ("GET",)),
        ("/whatsapp/webhook", ("POST",)),
    }


def test_server_requires_authenticated_sender_identities(server_module, monkeypatch):
    monkeypatch.setattr(
        server_module["Config"], "get", lambda: SimpleNamespace(whatsapp=SimpleNamespace(app_secret=""))
    )
    run = Mock()
    monkeypatch.setattr(server_module["IOHandler"], "run", run)
    with pytest.raises(ValueError, match="AK_WHATSAPP__APP_SECRET"):
        server_module["main"]()
    run.assert_not_called()
