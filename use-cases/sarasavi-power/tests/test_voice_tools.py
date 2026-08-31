"""VoiceToolExecutor: consent gating, persistence, and chat/call state sharing."""

from __future__ import annotations

import asyncio

from agentkernel.core import Runtime
from agentkernel.core import ToolContext as AKToolContext

import state
from voice.live_agent import VoiceToolExecutor

PHONE = "94770000001"


def _executor() -> VoiceToolExecutor:
    return VoiceToolExecutor(PHONE)


def test_unknown_tool_returns_error() -> None:
    result = asyncio.run(_executor().call("launch_rocket", {}))

    assert result["ok"] is False


def test_consent_gates_writes_through_the_voice_path() -> None:
    async def scenario():
        executor = _executor()
        denied = await executor.call("add_appliance", {"appliance": "refrigerator", "hours_per_day": 24})
        await executor.call("set_storage_consent", {"consent": True})
        allowed = await executor.call("add_appliance", {"appliance": "refrigerator", "hours_per_day": 24})
        await executor.call("set_storage_consent", {"consent": False})  # cleanup: erases profile
        return denied, allowed

    denied, allowed = asyncio.run(scenario())

    assert denied["ok"] is False and "consent" in denied["error"].lower()
    assert allowed["ok"] is True and allowed["added"] == "refrigerator"


def test_bad_arguments_return_structured_error_not_exception() -> None:
    async def scenario():
        executor = _executor()
        await executor.call("set_storage_consent", {"consent": True})
        result = await executor.call("add_appliance", {"appliance": "refrigerator", "wrong_arg": 1})
        await executor.call("set_storage_consent", {"consent": False})
        return result

    result = asyncio.run(scenario())

    assert result["ok"] is False and "argument" in result["error"]


def test_voice_writes_are_visible_to_the_text_chat_path() -> None:
    """The demo's money shot: a call and the chat share one session profile."""

    async def scenario():
        executor = _executor()
        await executor.call("set_storage_consent", {"consent": True})
        await executor.call("add_appliance", {"appliance": "ෆෑන් එක", "hours_per_day": 8})
        bill = await executor.call("compute_current_bill", {})

        # Text path: same session id, stock ToolContext, state.py accessors.
        runtime = Runtime.current()
        session = runtime.sessions().load(PHONE)
        ctx = AKToolContext(runtime, None, session, [])
        ctx.set()
        try:
            profile = state.load_profile()
        finally:
            ctx.reset()
        await executor.call("set_storage_consent", {"consent": False})
        return bill, profile

    bill, profile = asyncio.run(scenario())

    assert bill["ok"] is True and bill["total"] > 0
    assert profile["consent"] is True
    assert profile["appliances"][0]["key"] == "ceiling_fan"
