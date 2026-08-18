"""Schedule system tools — the agent-facing surface of the scheduling capability.

Registered on every agent (via ``SystemToolFactory``) when a ``schedule`` block is configured:
creation (``create_schedule``), reads (``list_schedules``/``get_schedule``) and management
(``update_schedule``/``delete_schedule``). All of them return JSON strings and turn failures into
``{"error": ...}`` strings — tools never raise into the framework.

Every tool acts as the user the run belongs to: the acting user published in the session's
volatile cache is the owner a created task is stored under and the identity later reads and
mutations are checked against, so an agent can never reach another user's schedules.
"""

import json
import logging
from typing import Any, Dict, Optional

from ..core.base import Session
from ..core.model import ScheduleSpec, SystemTool
from ..core.runtime import ACTING_USER_CACHE_KEY
from .manager import ScheduleManager
from .model import ScheduledTask

_log = logging.getLogger("ak.schedule.tools")

_DISABLED = json.dumps({"error": "scheduling capability is disabled"})

_NO_IDENTITY = json.dumps({"error": "scheduling requires a user identity: include user_id on the chat request"})


def _acting_user() -> Optional[str]:
    """The user the current run acts for, published in the session's volatile cache by ``Runtime``.

    :return: The acting user id, or None when the run carries no user identity.
    """
    session = Session.current()
    if session is None:
        return None
    return session.get_volatile_cache().get(ACTING_USER_CACHE_KEY)


def _current_session_id() -> Optional[str]:
    """The session a task created in this run belongs to.

    It is the session each occurrence runs in under ``session_mode`` reuse, and the base the
    per-occurrence session ids are derived from under ``session_mode`` new.

    :return: The current session id, or None outside a run.
    """
    session = Session.current()
    return session.id if session is not None else None


def _error_json(error: Exception) -> str:
    """Serialize a failure into the tool ``{"error": ...}`` JSON contract.

    :param error: The failure to report.
    :return: The error JSON.
    """
    return json.dumps({"error": str(error)})


def _task_json(task: ScheduledTask) -> Dict[str, Any]:
    """Agent-facing view of a task: the fields an agent can act on or report to the user.

    Flattened out of the stored record (whose provider reference and owner are machinery the agent
    has no use for) so a schedule reads back the same way it was asked for.

    :param task: The stored task.
    :return: The agent-facing projection.
    """
    return {
        "task_id": task.task_id,
        "prompt": task.prompt,
        "agent": task.agent,
        "status": task.status.value,
        "at": task.spec.at,
        "cron": task.spec.cron,
        "timezone": task.spec.timezone,
        "session_mode": task.spec.session_mode,
        "trigger_count": task.trigger_count,
        "last_triggered_at": task.last_triggered_at,
    }


async def create_schedule(
    prompt: str,
    cron: Optional[str] = None,
    at: Optional[str] = None,
    timezone: str = "UTC",
    session_mode: str = "reuse",
    agent: Optional[str] = None,
) -> str:
    """
    Schedule a prompt to run later, once or repeatedly, and return the scheduled task as JSON.

    Args:
        prompt: The instruction to run at the scheduled time. It runs with no further input, so
            make it self-contained.
        cron: Standard 5-field cron expression for a recurring schedule (e.g. "0 9 * * 1" for
            every Monday at 09:00). Give either cron or at, never both.
        at: Local wall-clock ISO-8601 timestamp for a one-time schedule (e.g.
            "2030-01-31T09:00:00"), without a UTC offset and in the future.
        timezone: IANA timezone the expression is evaluated in (e.g. "Asia/Colombo").
        session_mode: "reuse" to run each occurrence in this conversation, "new" to run each one
            in its own fresh session.
        agent: Name of the agent each occurrence runs on; omit for the default agent.

    Returns:
        JSON with task_id, prompt, agent, status, at, cron, timezone, session_mode,
        trigger_count, and last_triggered_at; or {"error": ...} on failure.
    """
    manager = ScheduleManager.get()
    if manager is None:
        return _DISABLED
    user_id = _acting_user()
    if user_id is None:
        return _NO_IDENTITY
    try:
        spec = ScheduleSpec(at=at, cron=cron, timezone=timezone, session_mode=session_mode)
        task = manager.create(user_id=user_id, prompt=prompt, spec=spec, agent=agent, session_id=_current_session_id())
        return json.dumps(_task_json(task))
    except Exception as exc:  # noqa: BLE001 — tools never raise into the framework
        _log.warning("create_schedule failed: %s", exc)
        return _error_json(exc)


async def list_schedules() -> str:
    """
    List the schedules belonging to the current user.

    Returns:
        JSON {"schedules": [{task_id, prompt, agent, status, at, cron, timezone, session_mode,
        trigger_count, last_triggered_at}, ...]}; or {"error": ...} on failure.
    """
    manager = ScheduleManager.get()
    if manager is None:
        return _DISABLED
    user_id = _acting_user()
    if user_id is None:
        return _NO_IDENTITY
    try:
        page = manager.list_tasks(user_id=user_id)
        return json.dumps({"schedules": [_task_json(task) for task in page.tasks]})
    except Exception as exc:  # noqa: BLE001 — tools never raise into the framework
        _log.warning("list_schedules failed: %s", exc)
        return _error_json(exc)


async def get_schedule(task_id: str) -> str:
    """
    Read one schedule of the current user.

    Args:
        task_id: Identifier returned when the schedule was created or listed.

    Returns:
        JSON with task_id, prompt, agent, status, at, cron, timezone, session_mode,
        trigger_count, and last_triggered_at; or {"error": ...} when it does not exist,
        belongs to someone else, or the read failed.
    """
    manager = ScheduleManager.get()
    if manager is None:
        return _DISABLED
    user_id = _acting_user()
    if user_id is None:
        return _NO_IDENTITY
    try:
        task = manager.get_task(task_id, user_id=user_id)
        if task is None:
            return json.dumps({"error": f"scheduled task {task_id} not found"})
        return json.dumps(_task_json(task))
    except Exception as exc:  # noqa: BLE001 — tools never raise into the framework
        _log.warning("get_schedule failed: %s", exc)
        return _error_json(exc)


async def update_schedule(
    task_id: str,
    prompt: str,
    cron: Optional[str] = None,
    at: Optional[str] = None,
    timezone: str = "UTC",
    session_mode: str = "reuse",
    status: str = "active",
) -> str:
    """
    Replace a schedule's prompt, timing and paused state, and return the updated task as JSON.

    Every field is replaced, not merged: send the schedule's full intended state, including the
    values that are not changing (read it first with get_schedule when unsure).

    Args:
        task_id: Identifier of the schedule to change.
        prompt: The instruction each occurrence runs.
        cron: Standard 5-field cron expression for a recurring schedule. Give either cron or at.
        at: Local wall-clock ISO-8601 timestamp for a one-time schedule, in the future.
        timezone: IANA timezone the expression is evaluated in.
        session_mode: "reuse" to run each occurrence in this conversation, "new" for a fresh
            session per occurrence.
        status: "active" to keep it running, or "paused" to stop it firing without cancelling it.

    Returns:
        JSON with the updated task_id, prompt, agent, status, at, cron, timezone, session_mode,
        trigger_count, and last_triggered_at; or {"error": ...} on failure.
    """
    manager = ScheduleManager.get()
    if manager is None:
        return _DISABLED
    user_id = _acting_user()
    if user_id is None:
        return _NO_IDENTITY
    try:
        amendment = {"prompt": prompt, "cron": cron, "at": at, "timezone": timezone, "session_mode": session_mode, "status": status}
        return json.dumps(_task_json(manager.update(task_id, amendment, user_id=user_id)))
    except Exception as exc:  # noqa: BLE001 — tools never raise into the framework
        _log.warning("update_schedule failed: %s", exc)
        return _error_json(exc)


async def delete_schedule(task_id: str) -> str:
    """
    Cancel a schedule so it never fires again. The record is kept, marked cancelled.

    Args:
        task_id: Identifier of the schedule to cancel.

    Returns:
        JSON with the cancelled task_id, prompt, agent, status, at, cron, timezone,
        session_mode, trigger_count, and last_triggered_at; or {"error": ...} on failure.
    """
    manager = ScheduleManager.get()
    if manager is None:
        return _DISABLED
    user_id = _acting_user()
    if user_id is None:
        return _NO_IDENTITY
    try:
        return json.dumps(_task_json(manager.cancel(task_id, user_id=user_id)))
    except Exception as exc:  # noqa: BLE001 — tools never raise into the framework
        _log.warning("delete_schedule failed: %s", exc)
        return _error_json(exc)


_GUIDANCE = (
    "[Scheduling]\n"
    "You can defer work: when the user asks for something to happen later or on a repeating "
    "rhythm, register it as a schedule instead of answering as if you had already done it. Each "
    "occurrence runs the prompt you stored, with no further input from the user, so write it as a "
    "complete self-contained instruction.\n"
    "Available tools:\n"
    "- create_schedule(prompt, cron, at, timezone, session_mode, agent): register a schedule; "
    "returns its task_id.\n"
    "- list_schedules(): list the current user's schedules.\n"
    "- get_schedule(task_id): read one schedule.\n"
    "- update_schedule(task_id, prompt, cron, at, timezone, session_mode, status): replace a "
    "schedule's full state (including status 'paused' to suspend it, 'active' to resume).\n"
    "- delete_schedule(task_id): cancel a schedule permanently.\n"
    "Timing: give exactly one of cron (standard 5-field expression, e.g. '0 9 * * 1' for Mondays "
    "at 09:00) or at (local wall-clock ISO-8601 timestamp in the future, e.g. "
    "'2030-01-31T09:00:00', with no UTC offset). Both are evaluated in timezone, an IANA name — "
    "ask the user for theirs rather than assuming UTC when the request implies a local time.\n"
    "session_mode 'reuse' (the default) runs each occurrence in this conversation, so the "
    "occurrence sees its history; 'new' runs each occurrence in a fresh session.\n"
    "update_schedule replaces every field rather than merging, so read the schedule first and "
    "resend the values that are not changing.\n"
    "Task ids are assigned by the system; never invent one — find a schedule with "
    "list_schedules.\n"
    'If a tool result contains an "error" field the operation FAILED: report the error to the '
    "user; never describe a schedule as created, changed or cancelled when it was not."
)


def get_schedule_tools() -> list[SystemTool]:
    """Build the schedule system tools; called by ``SystemToolFactory`` when the block is present.

    The capability's whole system-prompt section rides on the first tool's ``description`` (the
    sandbox pattern: ``SystemToolFactory.get_system_prompt_suffix()`` is appended to every agent's
    instructions via ``Agent._setup_system_prompt()``), so agents learn about scheduling
    automatically — agent authors never describe these tools in their own instructions. The
    remaining tools carry empty descriptions; their LLM-facing schemas come from the function
    docstrings when the tools are bound.

    :return: The schedule system tools.
    """
    return [
        SystemTool(name="create_schedule", description=_GUIDANCE, func=create_schedule),
        SystemTool(name="list_schedules", description="", func=list_schedules),
        SystemTool(name="get_schedule", description="", func=get_schedule),
        SystemTool(name="update_schedule", description="", func=update_schedule),
        SystemTool(name="delete_schedule", description="", func=delete_schedule),
    ]
