"""The A2A surface on a2a-sdk 1.x (#762): the card an agent publishes.

The card lists only what is actually exchanged, and it asks the A2UI capability, by agent name,
whether to declare A2UI, so the card and the labelling can never disagree.
"""

import pytest
from a2a.server.request_handlers.response_helpers import agent_card_to_dict
from a2a.types import AgentSkill

from agentkernel.a2ui.hook import A2UIPostHook
from agentkernel.core.builder import A2ACardBuilder
from agentkernel.core.config import AKConfig

AGENT = "expenses"
A2A_URL = "http://agents.test/a2a"


@pytest.fixture(autouse=True)
def _environment(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    monkeypatch.setenv("AK_A2A__URL", A2A_URL)
    AKConfig._reset()
    yield
    AKConfig._reset()


def _configure(monkeypatch, **env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    AKConfig._reset()


def _card(description="Files expense claims", skills=None):
    return A2ACardBuilder.build(name=AGENT, description=description, skills=skills or [])


class TestCard:
    def test_one_1_0_rest_interface_at_the_configured_url(self):
        [interface] = _card().supported_interfaces

        assert (interface.url, interface.protocol_binding, interface.protocol_version) == (f"{A2A_URL}/{AGENT}", "HTTP+JSON", "1.0")

    def test_the_served_card_carries_no_0_3_keys(self):
        served = agent_card_to_dict(_card())

        assert "url" not in served
        assert "preferredTransport" not in served
        assert served["supportedInterfaces"][0]["protocolVersion"] == "1.0"

    def test_modes_are_media_types_and_text_only_without_a2ui(self):
        card = _card()

        assert list(card.default_input_modes) == ["text/plain"]
        assert list(card.default_output_modes) == ["text/plain"]
        assert list(card.capabilities.extensions) == []
        assert card.capabilities.streaming is False

    def test_an_a2ui_agent_declares_the_extension_and_its_media_type(self, monkeypatch):
        _configure(monkeypatch, AK_A2UI__ENABLED="true")
        card = _card()

        assert list(card.default_output_modes) == ["text/plain", A2UIPostHook.MEDIA_TYPE]
        [extension] = card.capabilities.extensions
        assert extension.uri == A2UIPostHook.EXTENSION_URI
        assert extension.required is False

    def test_an_agent_outside_a2ui_scope_declares_neither(self, monkeypatch):
        _configure(monkeypatch, AK_A2UI__ENABLED="true", AK_A2UI__AGENTS='["someone-else"]')
        card = _card()

        assert list(card.default_output_modes) == ["text/plain"]
        assert list(card.capabilities.extensions) == []

    def test_a_non_string_description_becomes_empty_with_a_warning(self, caplog):
        with caplog.at_level("WARNING", logger="ak.builder"):
            card = _card(description=lambda: "dynamic instructions")

        assert card.description == ""
        assert AGENT in caplog.text

    def test_an_untagged_skill_is_tagged_with_the_agent_name(self):
        untagged = AgentSkill(id="file", name="file", description="File a claim", tags=[])
        tagged = AgentSkill(id="list", name="list", description="List claims", tags=["read"])

        card = _card(skills=[untagged, tagged])

        assert [list(skill.tags) for skill in card.skills] == [[AGENT], ["read"]]
