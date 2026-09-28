"""Tests for the agent graph's shape and its model pinning.

The model is pinned because the OpenAI Agents SDK otherwise defaults to gpt-4o, which is not
necessarily available on a given account, and because on a free tier the model choice is
really a rate-limit choice.
"""

import importlib

import agent


def test_every_agent_pins_a_model():
    # An agent added without a model would silently fall back to the SDK default.
    for item in agent.AGENTS:
        assert item.model, f"{item.name} does not pin a model"


def test_every_agent_shares_the_same_model():
    assert {item.model for item in agent.AGENTS} == {agent.MODEL}


def test_the_model_is_overridable(monkeypatch):
    monkeypatch.setenv("MATHRU_MODEL", "some-other-model")
    reloaded = importlib.reload(agent)
    try:
        assert reloaded.MODEL == "some-other-model"
        assert {item.model for item in reloaded.AGENTS} == {"some-other-model"}
    finally:
        monkeypatch.delenv("MATHRU_MODEL", raising=False)
        importlib.reload(agent)


def test_the_entry_agent_routes_but_holds_no_content_tools():
    triage = agent.mathru_triage_agent
    assert [tool.name for tool in triage.tools] == ["resolve_role"]
    assert {handoff.name for handoff in triage.handoffs} == {
        "intake_agent",
        "schedule_agent",
        "danger_sign_agent",
        "phm_agent",
    }


def test_schedule_agent_can_hand_back_to_intake():
    assert [handoff.name for handoff in agent.schedule_agent.handoffs] == ["intake_agent"]


def test_every_handoff_target_is_registered_with_the_module():
    # A handoff to an unregistered agent fails only at runtime.
    registered = {item.name for item in agent.AGENTS}
    for item in agent.AGENTS:
        for handoff in item.handoffs or []:
            assert handoff.name in registered, f"{handoff.name} is a handoff target but is not in AGENTS"
