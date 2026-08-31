"""Stored task model of the scheduling capability.

The chat-envelope side of the capability (``ScheduleSpec``) lives in ``core.model`` beside the
other wire models; this module owns the record the capability persists and returns.

Every field is a JSON primitive — timestamps included, as ISO-8601 UTC strings — because the
record is stored as one document by every backend and because trigger bodies built from it are
serialized with ``json.dumps`` before they enter a queue.
"""

import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel

from ..core.model import ScheduleSpec

# Placeholders the manager freezes into a trigger body at create/amend time. Each provider
# substitutes them with its own occurrence values (EventBridge with its context attributes,
# resolved by AWS at fire time; the local provider with values it mints when the timer fires),
# so a stored body template stays provider-neutral.
TOKEN_REQUEST_ID = "{ak.schedule.request_id}"
TOKEN_OCCURRENCE_TIME = "{ak.schedule.occurrence_time}"


def utc_now_iso() -> str:
    """Return the current UTC time in the ISO-8601 form the task record stores."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class ScheduleStatus(str, Enum):
    """Lifecycle state of a scheduled task."""

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ScheduledTask(BaseModel):
    """A chat request registered to run later, once (``spec.at``) or repeatedly (``spec.cron``).

    task_id: str : AK-minted identifier, also the name the provider registers under
    user_id: str : owning user; every mutation is checked against it
    prompt: str : the prompt each occurrence runs
    agent: str | None : the agent each occurrence runs on, or None for the default
    session_id: str : originating session (``session_mode`` reuse) or the base for
        per-occurrence session ids (``session_mode`` new)
    spec: ScheduleSpec : the occurrence rule this task was created from
    status: ScheduleStatus : lifecycle state
    provider_ref: str | None : handle the provider registered the task under (an EventBridge
        schedule ARN, the task id for the local provider)
    created_at / updated_at: str : ISO-8601 UTC timestamps
    last_triggered_at: str | None : occurrence time of the most recent trigger
    trigger_count: int : number of occurrences fired so far
    last_request_id: str | None : request id of the most recent occurrence, for correlating
        the task with the run it produced
    """

    task_id: str
    user_id: str
    prompt: str
    agent: Optional[str] = None
    session_id: str
    spec: ScheduleSpec
    status: ScheduleStatus = ScheduleStatus.ACTIVE
    provider_ref: Optional[str] = None
    created_at: str
    updated_at: str
    last_triggered_at: Optional[str] = None
    trigger_count: int = 0
    last_request_id: Optional[str] = None

    def apply_trigger(self, request_id: Optional[str], occurred_at: str, completed: bool) -> "ScheduledTask":
        """Advance the occurrence bookkeeping after one of this task's triggers fired.

        What an occurrence records, and when it closes the task, is the same on every backend —
        a store's remaining job is only to load the record and write it back — so the rule lives
        here rather than once per store. A cancellation outranks a completion: a task cancelled
        between the fire and the record must not come back as completed.

        :param request_id: Request id of the run the occurrence produced, when known.
        :param occurred_at: ISO-8601 UTC timestamp of the occurrence.
        :param completed: Whether this was the task's final occurrence.
        :return: This task, advanced in place, so a store can write it back in one expression.
        """
        self.last_triggered_at = occurred_at
        self.last_request_id = request_id
        self.trigger_count += 1
        self.updated_at = utc_now_iso()
        if completed and self.status is not ScheduleStatus.CANCELLED:
            self.status = ScheduleStatus.COMPLETED
        return self


class ScheduledTaskPage(BaseModel):
    """A page of scheduled tasks and the cursor for the next one (None on the last page)."""

    tasks: List[ScheduledTask]
    next_cursor: Optional[str] = None
