from __future__ import annotations

import inspect

import pytest
from agentkernel.api import RESTAPI

from agent import AGENTS
from startup import require_gemini_config, require_whatsapp_config


def test_agent_graph_has_one_way_specialist_transfers() -> None:
    graph = {agent.name: len(agent.sub_agents) for agent in AGENTS}

    assert graph == {
        "orchestrator": 3,
        "intake": 0,
        "analysis": 0,
        "recommendation": 0,
    }


def test_specialists_cannot_transfer_back_or_sideways() -> None:
    """One-way routing: a specialist answers, then the next turn restarts at the
    orchestrator instead of the conversation getting stuck inside the specialist."""
    for agent in AGENTS:
        if agent.name == "orchestrator":
            assert not agent.disallow_transfer_to_parent
            continue
        assert agent.disallow_transfer_to_parent
        assert agent.disallow_transfer_to_peers


def test_rest_api_uses_handlers_list_signature() -> None:
    parameters = inspect.signature(RESTAPI.run).parameters

    assert "handlers" in parameters
    assert "handler" not in parameters


def test_startup_check_rejects_missing_or_placeholder_key(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="GOOGLE_API_KEY"):
        require_gemini_config()

    monkeypatch.setenv("GOOGLE_API_KEY", "your-gemini-api-key-here")
    with pytest.raises(SystemExit, match="placeholder"):
        require_gemini_config()


def test_startup_check_accepts_gemini_api_key_alias(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "redacted-test-key")
    monkeypatch.delenv("SARASAVI_MODEL", raising=False)

    assert require_gemini_config() == "gemini-2.5-flash"


def test_startup_check_skips_key_requirement_on_vertex_ai(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
    monkeypatch.delenv("SARASAVI_MODEL", raising=False)

    assert require_gemini_config() == "gemini-2.5-flash"


def test_startup_check_returns_configured_model(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "redacted-test-key")
    monkeypatch.setenv("SARASAVI_MODEL", "test-model")

    assert require_gemini_config() == "test-model"


def test_whatsapp_startup_check_lists_missing_meta_values(monkeypatch) -> None:
    names = (
        "AK_WHATSAPP__VERIFY_TOKEN",
        "AK_WHATSAPP__ACCESS_TOKEN",
        "AK_WHATSAPP__PHONE_NUMBER_ID",
        "AK_WHATSAPP__APP_SECRET",
    )
    for name in names:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(SystemExit, match="Meta WhatsApp configuration") as exc_info:
        require_whatsapp_config()

    for name in names:
        assert name in str(exc_info.value)


def test_whatsapp_startup_check_accepts_real_values(monkeypatch) -> None:
    monkeypatch.setenv("AK_WHATSAPP__VERIFY_TOKEN", "sarasavi-secret")
    monkeypatch.setenv("AK_WHATSAPP__ACCESS_TOKEN", "EAAB-real-token")
    monkeypatch.setenv("AK_WHATSAPP__PHONE_NUMBER_ID", "123456789")
    monkeypatch.setenv("AK_WHATSAPP__APP_SECRET", "abcdef123456")

    assert require_whatsapp_config() is None
