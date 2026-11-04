"""
Pause and resume over AG-UI (spec `docs/specs/606-human-in-the-loop/`, iteration 9).

A pause is a **terminal outcome** in this protocol, not a mid-stream event: the run ends with
`RunFinishedEvent(outcome=RunFinishedInterruptOutcome(...))`. So the handler grows a third terminal
shape rather than the mapper gaining a case, and `AGUIMapper.to_agui` keeps returning None for
`RunPaused` without anything being dropped.

The resume side is the only surface with no run id to send — `ResumeEntry` carries an interrupt id
and nothing else — so the run is resolved from the interruption ids. That is why
`AgentResumeRequestAny.run_id` is optional and why interruption ids must be unique across a
session's records.
"""

import json
from contextlib import contextmanager
from typing import Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentkernel.auth import Authoriser
from agentkernel.core.base import Agent, Runner
from agentkernel.core.config import _AGUIConfig
from agentkernel.core.event import PausedInterruption, RunPaused, TextDelta
from agentkernel.core.model import AgentReplyText, AgentResumeRequestAny
from agentkernel.core.paused_run import PausedRunState
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.integration.agui import AGUIRequestHandler
from agentkernel.integration.agui.run_input import AGUIRunInput

GOOD_TOKEN = "good-token"
AUTH = {"Authorization": f"Bearer {GOOD_TOKEN}"}


class StaticAuthoriser(Authoriser):
    def authorise(self, token: str) -> Optional[str]:
        return "u1" if token == GOOD_TOKEN else None


class PausingRunner(Runner):
    """Pauses on the first turn, answers on resume. Records what the resume handed it."""

    supports_pause = True

    def __init__(self, name="pausing", interruptions=None, pause_again=False):
        super().__init__(name)
        self._interruptions = interruptions or [PausedInterruption(id="i1", kind="tool_call", tool_name="refund", arguments='{"amount": 100}')]
        self._pause_again = pause_again
        self.resumed_with = None
        self.resumed_requests = None

    @property
    def supports_streaming(self) -> bool:
        return True

    async def run(self, agent, session, requests):
        return AgentReplyText(response="unused")

    async def stream(self, agent, session, requests):
        record = PausedRunState.add(session, agent=agent.name, interruptions=self._interruptions, payload={"state": "blob"})
        yield RunPaused(run_id=record.id, agent=agent.name, interruptions=record.interruptions)

    async def resume(self, agent, session, requests, decisions, record):
        self.resumed_with = decisions
        # Clearing is the adapter's, on its success path — Runtime deliberately does not tidy up,
        # because it cannot tell a failed resume from an ordinary reply. A double that skipped this
        # would model a contract no real adapter follows.
        PausedRunState.clear(session, record.id)
        return AgentReplyText(response="resumed")

    async def resume_stream(self, agent, session, requests, decisions, record):
        self.resumed_with = decisions
        self.resumed_requests = requests
        yield TextDelta(message_id="m2", content="resumed")
        PausedRunState.clear(session, record.id)


class PausingAgent(Agent):
    def __init__(self, name="refunds", runner=None):
        super().__init__(name, runner or PausingRunner())

    def get_a2a_card(self):
        return None

    def get_description(self):
        return "pauses"

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


@contextmanager
def serving(monkeypatch, agents, agui_cfg=None):
    from agentkernel.core.config import AKConfig

    cfg = AKConfig.get()
    monkeypatch.setattr(cfg, "agui", agui_cfg if agui_cfg is not None else _AGUIConfig(), raising=False)
    Runtime._system_pre_hooks = []
    Runtime._system_post_hooks = []
    runtime = Runtime(InMemorySessionStore())
    for agent in agents:
        runtime.register(agent)
    try:
        with runtime:
            app = FastAPI()
            app.include_router(AGUIRequestHandler(authoriser=StaticAuthoriser()).get_router())
            yield TestClient(app), runtime
    finally:
        Runtime._system_pre_hooks = None
        Runtime._system_post_hooks = None


def body(**overrides):
    payload = {
        "threadId": "session-1",
        "runId": "run-1",
        "state": None,
        "messages": [{"id": "m1", "role": "user", "content": "refund my order"}],
        "tools": [],
        "context": [],
        "forwardedProps": None,
    }
    payload.update(overrides)
    return payload


def events(response) -> list[dict]:
    return [json.loads(line[len("data: ") :]) for line in response.text.splitlines() if line.startswith("data: ")]


class TestTheInterruptTerminalOutcome:
    def test_the_run_ends_with_an_interrupt_outcome(self, monkeypatch):
        with serving(monkeypatch, [PausingAgent()]) as (client, _):
            response = client.post("/agui/refunds", json=body(), headers=AUTH)

        finished = events(response)[-1]
        assert finished["type"] == "RUN_FINISHED"
        assert finished["outcome"]["type"] == "interrupt"
        assert [i["id"] for i in finished["outcome"]["interrupts"]] == ["i1"]

    def test_the_kind_passes_through_as_reason_untranslated(self, monkeypatch):
        """`reason` is a free-form string, so no translation table is needed — nor should one exist."""
        with serving(monkeypatch, [PausingAgent()]) as (client, _):
            response = client.post("/agui/refunds", json=body(), headers=AUTH)

        assert events(response)[-1]["outcome"]["interrupts"][0]["reason"] == "tool_call"

    def test_what_the_protocol_has_no_field_for_rides_in_metadata(self, monkeypatch):
        """Rather than being forced into response_schema, which means a JSON Schema."""
        with serving(monkeypatch, [PausingAgent()]) as (client, _):
            response = client.post("/agui/refunds", json=body(), headers=AUTH)

        interrupt = events(response)[-1]["outcome"]["interrupts"][0]
        assert interrupt["metadata"]["tool_name"] == "refund"
        assert interrupt["metadata"]["arguments"] == '{"amount": 100}'

    def test_an_ordinary_run_still_finishes_without_an_outcome(self, monkeypatch):
        class PlainRunner(PausingRunner):
            async def stream(self, agent, session, requests):
                yield TextDelta(message_id="m1", content="hi")

        with serving(monkeypatch, [PausingAgent(runner=PlainRunner())]) as (client, _):
            response = client.post("/agui/refunds", json=body(), headers=AUTH)

        finished = events(response)[-1]
        assert finished["type"] == "RUN_FINISHED"
        assert finished.get("outcome") is None

    def test_the_pause_is_not_emitted_mid_stream(self, monkeypatch):
        """It is the run's outcome, so it must not also appear as an event in the body."""
        with serving(monkeypatch, [PausingAgent()]) as (client, _):
            response = client.post("/agui/refunds", json=body(), headers=AUTH)

        assert [e["type"] for e in events(response)] == ["RUN_STARTED", "RUN_FINISHED"]


class TestResumingOverAGUI:
    def test_a_decision_resolves_the_run_from_its_interruption_id(self, monkeypatch):
        """The only surface with no run id to send: the protocol has no field for one."""
        agent = PausingAgent()
        with serving(monkeypatch, [agent]) as (client, _):
            client.post("/agui/refunds", json=body(), headers=AUTH)
            resume_body = body(
                messages=[{"id": "m1", "role": "user", "content": "refund my order"}, {"id": "m2", "role": "assistant", "content": "checking"}],
                resume=[{"interruptId": "i1", "status": "resolved", "payload": {"approved": True}}],
            )
            response = client.post("/agui/refunds", json=resume_body, headers=AUTH)

        assert agent.runner.resumed_with[0].id == "i1"
        assert events(response)[-1]["type"] == "RUN_FINISHED"

    def test_the_resume_request_reaches_the_runner(self, monkeypatch):
        agent = PausingAgent()
        with serving(monkeypatch, [agent]) as (client, _):
            client.post("/agui/refunds", json=body(), headers=AUTH)
            client.post(
                "/agui/refunds",
                json=body(
                    messages=[{"id": "m2", "role": "assistant", "content": "checking"}],
                    resume=[{"interruptId": "i1", "status": "resolved"}],
                ),
                headers=AUTH,
            )

        assert any(isinstance(r, AgentResumeRequestAny) for r in agent.runner.resumed_requests)

    def test_the_agent_comes_from_the_url_not_the_body(self, monkeypatch):
        """RunAgentInput has no agent field; AG-UI carries it in the route instead."""
        refunds, billing = PausingAgent(name="refunds"), PausingAgent(name="billing")
        with serving(monkeypatch, [refunds, billing]) as (client, _):
            client.post("/agui/refunds", json=body(), headers=AUTH)
            client.post(
                "/agui/refunds",
                json=body(messages=[{"id": "m2", "role": "assistant", "content": "x"}], resume=[{"interruptId": "i1", "status": "resolved"}]),
                headers=AUTH,
            )

        assert refunds.runner.resumed_with is not None
        assert billing.runner.resumed_with is None


class TestStatusMapsWithoutFlattening:
    """Two statuses on the wire, three in Agent Kernel — and `cancelled` must not read as `denied`."""

    @pytest.mark.parametrize(
        "entry,expected",
        [
            ({"interruptId": "i1", "status": "cancelled"}, "cancelled"),
            ({"interruptId": "i1", "status": "resolved", "payload": True}, "approved"),
            ({"interruptId": "i1", "status": "resolved", "payload": False}, "denied"),
            ({"interruptId": "i1", "status": "resolved", "payload": "large"}, "approved"),
            ({"interruptId": "i1", "status": "resolved"}, "approved"),
        ],
    )
    def test_each_entry_maps_to_the_right_verb(self, entry, expected):
        run_input = AGUIRunInput.parse(body(messages=[{"id": "m1", "role": "user", "content": "hi"}], resume=[entry]))

        assert AGUIRunInput.to_resume(run_input).decisions[0].status == expected

    def test_a_refusal_carries_no_wording_over_this_surface(self):
        """AG-UI has no field for one, and Agent Kernel does not reserve keys inside `payload` to
        smuggle it — the SDK states `payload` is "the answer the agent asked for". `denied` still
        reaches the model as a refusal distinct from `cancelled`, which is the distinction that
        matters; a client needing the human's words uses REST, where `message` is its own field.
        """
        run_input = AGUIRunInput.parse(body(resume=[{"interruptId": "i1", "status": "resolved", "payload": False}]))
        decision = AGUIRunInput.to_resume(run_input).decisions[0]

        assert (decision.status, decision.message) == ("denied", None)

    def test_a_boolean_verdict_is_not_forwarded_as_an_answer(self):
        """`true` answers "may I?" and is nothing more. Forwarding it would hand an adapter a
        structured answer nobody gave, which OpenAI refuses since `approve()` takes no value.
        """
        run_input = AGUIRunInput.parse(body(resume=[{"interruptId": "i1", "status": "resolved", "payload": True}]))

        assert AGUIRunInput.to_resume(run_input).decisions[0].payload is None

    def test_an_answer_using_a_reserved_sounding_key_survives(self):
        """Nothing is reserved, so a question whose answer happens to be shaped like one is safe."""
        run_input = AGUIRunInput.parse(body(resume=[{"interruptId": "i1", "status": "resolved", "payload": {"message": "Dear customer"}}]))
        decision = AGUIRunInput.to_resume(run_input).decisions[0]

        assert decision.payload == {"message": "Dear customer"}
        assert decision.message is None

    def test_the_payload_is_carried_through_untouched(self):
        run_input = AGUIRunInput.parse(body(resume=[{"interruptId": "i1", "status": "resolved", "payload": ["damaged", "wrong_item"]}]))

        assert AGUIRunInput.to_resume(run_input).decisions[0].payload == ["damaged", "wrong_item"]

    def test_no_run_id_is_set(self):
        run_input = AGUIRunInput.parse(body(resume=[{"interruptId": "i1", "status": "resolved"}]))

        assert AGUIRunInput.to_resume(run_input).run_id is None


class TestThePromptTheClientDidNotSend:
    """
    AG-UI replays the whole conversation, so "the last user message" is not "this turn's prompt".

    Reaching past the assistant's reply to grab the original prompt would re-send the turn that
    caused the pause — and OpenAI and ADK reject a prompt riding beside a decision, so the run would
    fail with an error blaming the client for something the mapper invented.
    """

    def test_a_stale_history_prompt_is_not_re_sent(self):
        run_input = AGUIRunInput.parse(
            body(
                messages=[{"id": "m1", "role": "user", "content": "refund my order"}, {"id": "m2", "role": "assistant", "content": "checking"}],
                resume=[{"interruptId": "i1", "status": "resolved"}],
            )
        )

        assert [type(r).__name__ for r in AGUIRunInput.to_requests(run_input)] == ["AgentResumeRequestAny"]

    def test_no_prompt_is_derived_however_the_history_ends(self):
        """A paused run emits no assistant reply, so the conversation still ends with the prompt
        that caused the pause. Any rule for picking a "new" message out of replayed history is a
        guess, and this is the case where the guess sends a prompt beside a decision."""
        ends_with_user = body(
            messages=[{"id": "m1", "role": "user", "content": "refund my order"}],
            resume=[{"interruptId": "i1", "status": "resolved"}],
        )
        ends_with_assistant = body(
            messages=[
                {"id": "m1", "role": "user", "content": "refund my order"},
                {"id": "m2", "role": "assistant", "content": "checking"},
            ],
            resume=[{"interruptId": "i1", "status": "resolved"}],
        )

        for payload in (ends_with_user, ends_with_assistant):
            requests = AGUIRunInput.to_requests(AGUIRunInput.parse(payload))
            assert [type(r).__name__ for r in requests] == ["AgentResumeRequestAny"]

    def test_a_resume_with_no_messages_at_all_is_accepted(self):
        """Prompt **or** resume — the same rule the REST, WebSocket and thread surfaces apply."""
        run_input = AGUIRunInput.parse(body(messages=[], resume=[{"interruptId": "i1", "status": "resolved"}]))

        assert [type(r).__name__ for r in AGUIRunInput.to_requests(run_input)] == ["AgentResumeRequestAny"]

    def test_a_body_with_neither_is_still_rejected(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            AGUIRunInput.parse(body(messages=[{"id": "m1", "role": "assistant", "content": "hi"}]))

        assert exc.value.status_code == 400


class TestTwoRunsOutstanding:
    """
    Resolving by interruption id only works while those ids are unique across a session's records.

    This is the case that makes the uniqueness rule load-bearing rather than tidy: with two pauses
    open and no run id on the wire, the ids are the only thing that can tell them apart.
    """

    @staticmethod
    def _two_pauses(monkeypatch):
        class TwoRunner(PausingRunner):
            def __init__(self):
                super().__init__()
                self._turn = 0

            async def stream(self, agent, session, requests):
                self._turn += 1
                record = PausedRunState.add(
                    session,
                    agent=agent.name,
                    interruptions=[PausedInterruption(id=f"i{self._turn}", kind="tool_call", tool_name="refund")],
                    payload={"turn": self._turn},
                )
                yield RunPaused(run_id=record.id, agent=agent.name, interruptions=record.interruptions)

        return PausingAgent(runner=TwoRunner())

    def test_each_run_is_resolved_by_its_own_interruption_id(self, monkeypatch):
        agent = self._two_pauses(monkeypatch)
        with serving(monkeypatch, [agent]) as (client, runtime):
            client.post("/agui/refunds", json=body(), headers=AUTH)
            client.post("/agui/refunds", json=body(), headers=AUTH)
            assert len(PausedRunState.list(runtime.sessions().load("session-1"))) == 2

            response = client.post(
                "/agui/refunds",
                json=body(messages=[], resume=[{"interruptId": "i2", "status": "resolved"}]),
                headers=AUTH,
            )

        assert agent.runner.resumed_with[0].id == "i2"
        assert events(response)[-1]["type"] == "RUN_FINISHED"

    def test_answering_one_leaves_the_other_open(self, monkeypatch):
        agent = self._two_pauses(monkeypatch)
        with serving(monkeypatch, [agent]) as (client, runtime):
            client.post("/agui/refunds", json=body(), headers=AUTH)
            client.post("/agui/refunds", json=body(), headers=AUTH)
            client.post("/agui/refunds", json=body(messages=[], resume=[{"interruptId": "i1", "status": "resolved"}]), headers=AUTH)

            remaining = PausedRunState.list(runtime.sessions().load("session-1"))

        assert [i.id for record in remaining for i in record.interruptions] == ["i2"]

    def test_decisions_spanning_both_runs_are_refused(self, monkeypatch):
        """One resume addresses one run; spanning two is a failed resume, not a guess."""
        agent = self._two_pauses(monkeypatch)
        with serving(monkeypatch, [agent]) as (client, runtime):
            client.post("/agui/refunds", json=body(), headers=AUTH)
            client.post("/agui/refunds", json=body(), headers=AUTH)

            response = client.post(
                "/agui/refunds",
                json=body(messages=[], resume=[{"interruptId": "i1", "status": "resolved"}, {"interruptId": "i2", "status": "resolved"}]),
                headers=AUTH,
            )
            still_open = PausedRunState.list(runtime.sessions().load("session-1"))

        assert events(response)[-1]["type"] == "RUN_ERROR"
        assert agent.runner.resumed_with is None
        assert len(still_open) == 2
