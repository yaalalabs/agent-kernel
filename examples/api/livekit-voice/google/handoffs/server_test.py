"""Handoffs example tests: the handoff rule, the technician booking and the call log. No model, LiveKit or network."""

import asyncio
import logging
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


def test_a_technician_visit_is_answered_once_the_dispatch_system_confirms_it(monkeypatch):
    monkeypatch.setattr(server, "DISPATCH_SECONDS", 0.01)

    answer = asyncio.run(server.book_technician("A-1042", "Friday"))

    assert answer.startswith("The technician visit for account A-1042 on Friday is confirmed") and "TEC-4821" in answer
    assert server.dispatch.booking == set()


def test_a_second_booking_for_the_same_account_is_refused_while_the_first_is_confirmed(monkeypatch):
    monkeypatch.setattr(server, "DISPATCH_SECONDS", 0.1)

    async def book_at_once():
        return await asyncio.gather(
            server.book_technician("A-1042", "Friday"),
            server.book_technician("A-1042", "Friday"),
            server.book_technician("A-2000", "Monday"),
        )

    first, again, other = asyncio.run(book_at_once())

    assert "confirmed" in first and "confirmed" in other
    assert "already being booked" in again
    assert server.dispatch.booking == set()


def test_the_supervisor_carries_the_rule():
    assert server.supervisor.before_tool_callback is server.require_account


def test_the_call_log_writes_both_sides_of_the_call(caplog):
    log = server.CallLog()

    with caplog.at_level(logging.INFO, logger="server"):
        asyncio.run(
            log.on_event(
                None, None, server.RealtimeEvent(type="caller_said", session_id="room_01", text="My bill is high.")
            )
        )
        asyncio.run(
            log.on_event(
                None,
                None,
                server.RealtimeEvent(type="agent_said", session_id="room_01", agent="billing", text="Let me check."),
            )
        )

    assert "caller: My bill is high." in caplog.text
    assert "billing: Let me check." in caplog.text
