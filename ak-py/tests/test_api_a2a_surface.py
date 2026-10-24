"""The A2A surface on a2a-sdk 1.x (#762): it imports, the card an agent publishes, the routes served.

The card lists only what is actually exchanged, and it asks the A2UI capability, by agent name,
whether to declare A2UI, so the card and the labelling can never disagree.
"""

import subprocess
import sys

import httpx
import pytest
from a2a.server.request_handlers.response_helpers import agent_card_to_dict
from a2a.types import AgentSkill

from agentkernel.a2ui.hook import A2UIPostHook
from agentkernel.api.a2a.a2a import A2A
from agentkernel.api.http import RESTAPI
from agentkernel.core.base import Agent, Runner
from agentkernel.core.builder import A2ACardBuilder
from agentkernel.core.config import AKConfig
from agentkernel.core.runtime import Runtime

AGENT = "expenses"
CARDLESS = "cardless"
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


class TestImports:
    @pytest.mark.parametrize("module", ["agentkernel.api.a2a.a2a", "agentkernel.api.a2a.handler"])
    def test_the_a2a_modules_import(self, module):
        """The #762 bug: on a2a-sdk 1.x these failed to import, and no test imported them."""
        result = subprocess.run([sys.executable, "-c", f"import {module}"], capture_output=True, text=True)

        assert result.returncode == 0, result.stderr


class _NoRunner(Runner):
    async def run(self, agent, session, requests):  # pragma: no cover - routes are read, never run
        raise AssertionError("not run")

    async def stream(self, agent, session, requests):  # pragma: no cover
        raise NotImplementedError()
        yield


class _Agent(Agent):
    def __init__(self, name: str, with_card: bool = True):
        super().__init__(name, _NoRunner("NoRunner"))
        self._with_card = with_card

    def get_description(self) -> str:
        return "Files expense claims"

    def get_a2a_card(self):
        return A2ACardBuilder.build(name=self.name, description=self.get_description(), skills=[]) if self._with_card else None

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


class TestRoutes:
    """What the app serves per agent, built the way RESTAPI builds it."""

    @pytest.fixture(autouse=True)
    def _agents(self, monkeypatch):
        _configure(monkeypatch, AK_A2A__ENABLED="true")
        saved = (dict(A2A._cards), dict(A2A._executors), A2A._built)
        A2A._cards, A2A._executors, A2A._built = {}, {}, False
        agents = [_Agent(AGENT), _Agent(CARDLESS, with_card=False)]
        for agent in agents:
            Runtime.current().register(agent)
        yield
        for agent in agents:
            Runtime.current().deregister(agent)
        A2A._cards, A2A._executors, A2A._built = saved

    async def _request(self, method: str, path: str) -> httpx.Response:
        app = RESTAPI.build_app(handlers=[])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ak.test") as http:
            return await http.request(method, path, headers={"A2A-Version": "1.0"})

    async def _get(self, path: str) -> httpx.Response:
        return await self._request("GET", path)

    @pytest.mark.asyncio
    async def test_the_1_0_routes_are_served(self):
        """Checked over HTTP: a task list answers, an unknown task is the protocol's own not-found."""
        assert (await self._get(f"/a2a/{AGENT}/tasks")).status_code == 200
        unknown_task = await self._get(f"/a2a/{AGENT}/tasks/no-such-task")
        assert unknown_task.status_code == 404
        assert unknown_task.json()["error"]["status"] == "NOT_FOUND"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method, path",
        [
            ("POST", f"/a2a/{AGENT}/v1/message:send"),  # 0.3 compatibility stays off (D1)
            ("GET", f"/a2a/{AGENT}/v1/tasks"),
            ("GET", f"/a2a/{AGENT}/some-tenant/tasks"),  # the SDK's /{tenant} mount is not served
        ],
    )
    async def test_neither_0_3_nor_tenant_routes_are_served(self, method, path):
        response = await self._request(method, path)

        assert response.status_code == 404
        assert response.json() == {"detail": "Not Found"}  # FastAPI's, not the A2A handler's

    @pytest.mark.asyncio
    async def test_the_well_known_card_is_the_1_0_shape_with_an_etag(self):
        response = await self._get(f"/a2a/{AGENT}/.well-known/agent-card.json")

        assert response.status_code == 200
        assert "etag" in response.headers
        card = response.json()
        assert card["supportedInterfaces"][0]["url"] == f"{A2A_URL}/{AGENT}"
        assert "url" not in card and "preferredTransport" not in card

    @pytest.mark.asyncio
    async def test_an_unknown_agents_card_is_not_found(self):
        response = await self._get("/a2a/nobody/.well-known/agent-card.json")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_the_catalog_lists_the_served_cards(self):
        response = await self._get("/a2a/catalog")

        assert response.status_code == 200
        [card] = response.json()["cards"]
        assert card["name"] == AGENT

    @pytest.mark.asyncio
    async def test_an_agent_without_a_card_is_skipped_with_a_warning(self, caplog):
        with caplog.at_level("WARNING", logger="ak.a2a"):
            card = await self._get(f"/a2a/{CARDLESS}/.well-known/agent-card.json")

        assert f"Agent '{CARDLESS}' has no A2A card" in caplog.text
        assert card.status_code == 404
        assert (await self._request("POST", f"/a2a/{CARDLESS}/message:send")).status_code == 404
