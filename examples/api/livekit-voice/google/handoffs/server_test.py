"""Handoffs example tests: the handoff rule, the background confirmation and the call log. No model, LiveKit or network."""

import asyncio
import logging
import time
from types import SimpleNamespace

import server

TRANSFER = SimpleNamespace(name="transfer_to_agent")


def context(**state):
    return SimpleNamespace(state=dict(state))


def test_a_transfer_to_a_specialist_waits_for_a_verified_account():
    refused = server.require_account(TRANSFER, {"agent_name": "billing"}, context())

    assert "verify_account" in refused["result"]
    assert server.require_account(TRANSFER, {"agent_name": "tech_support"}, context(account_id="A-1042")) is None


def test_other_tools_and_other_transfers_are_not_held_back():
    assert server.require_account(SimpleNamespace(name="verify_account"), {"account_id": "A-1042"}, context()) is None
    assert server.require_account(TRANSFER, {"agent_name": "supervisor"}, context()) is None


def test_verifying_an_account_records_it_for_the_whole_call():
    state = context()

    assert "verified" in server.verify_account(" a-1042 ", state)
    assert state.state["account_id"] == "A-1042"
    assert "no account" in server.verify_account("1042", context())


def test_a_technician_visit_is_confirmed_into_the_call_in_the_background(monkeypatch):
    posts = []

    class FakeCall:
        def __init__(self, session_id):
            self.session_id = session_id

        def post_when_idle(self, text, key=None, expires_after=600.0):
            posts.append((self.session_id, text, key))
            return True

    monkeypatch.setattr(server, "RealtimeCall", FakeCall)
    monkeypatch.setattr(server, "DISPATCH_SECONDS", 0.0)
    monkeypatch.setattr(server.AKToolContext, "get", staticmethod(lambda: SimpleNamespace(session=SimpleNamespace(id="room_01"))))

    answer = server.book_technician("A-1042", "Friday")

    assert "confirm" in answer
    deadline = time.monotonic() + 2
    while not posts and time.monotonic() < deadline:
        time.sleep(0.01)
    [(session_id, text, key)] = posts
    assert (session_id, key) == ("room_01", "dispatch")
    assert text.startswith("[Dispatch system]") and "TEC-4821" in text


def test_the_supervisor_carries_the_rule_and_the_call_log():
    assert server.supervisor.before_tool_callback is server.require_account
    [hook] = server.module.get_agent("supervisor").realtime_hooks
    assert isinstance(hook, server.CallLog)


def test_the_call_log_writes_both_sides_of_the_call(caplog):
    log = server.CallLog()

    with caplog.at_level(logging.INFO, logger="server"):
        asyncio.run(log.on_event(None, None, server.RealtimeEvent(type="caller_said", session_id="room_01", text="My bill is high.")))
        asyncio.run(log.on_event(None, None, server.RealtimeEvent(type="agent_said", session_id="room_01", agent="billing", text="Let me check.")))

    assert "caller: My bill is high." in caplog.text
    assert "billing: Let me check." in caplog.text
