"""
The paused-run record and the single accessor every read and write of it goes through.

When a framework stops mid-run to ask a human something, the state needed to continue is opaque to
Agent Kernel and must outlive the process: the decision may arrive an hour later, on another
replica. It is written into the session's non-volatile cache, which `SessionStore.store()` already
pickles and persists, so no new backend, table or config block is involved.

The key holds a **list**. How many paused runs a session can really have is the framework's
business, not Agent Kernel's: only OpenAI can hold two resumable runs at once, while LangGraph,
Pydantic AI and Google ADK keep a single thread per session. Whether a new pause appends or replaces
is therefore the adapter's call, since only it knows whether the earlier one is still resumable.

Accepted risk, documented rather than hidden: the non-volatile cache is application space, so an
application calling `get_non_volatile_cache().clear()` discards pending decisions. The `ak.` key
prefix marks the key as framework-owned, and the user-facing docs say so.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, List, Optional

from pydantic import BaseModel, ValidationError

from .base import Session
from .config import AKConfig
from .event import PausedInterruption
from .util.picklable import first_unpicklable_entry, not_picklable

_log = logging.getLogger("ak.paused_run")

AK_PAUSED_RUNS_KEY = "ak.paused_runs"


class PausedRun(BaseModel):
    """
    One paused run: a framework-agnostic envelope around an opaque payload.

    id: str : assigned by PausedRunState.add. Agent Kernel has no other notion of an individual
        run, and a client needs one to say which pause it is answering
    agent: str : the agent that paused. Also identifies the framework, since an agent resolves to
        its runner, which is why no separate runner name is stored
    created_at: str : ISO-8601 UTC, for diagnostics and operator triage only
    interruptions: list[PausedInterruption] : the same list carried on the reply, so a resume can be
        validated without deserialising the payload
    payload: Any : per-framework resume state, opaque to core and never sent to a client. Must be
        picklable
    """

    id: str
    agent: str
    created_at: str
    interruptions: List[PausedInterruption]
    payload: Any = None


class PausedRunState:
    """
    Accessors for the paused runs a session holds.

    Static methods over the session's non-volatile cache, shaped on AGUIState: the key name is
    spelled once here and no caller touches the cache for paused runs directly. Deliberately not a
    Runner method, because Runtime must read a record to validate a resume and is not a Runner,
    while adapters must write one — a standalone class is the only home both can reach.

    Named State rather than Store because every *Store in Agent Kernel is a pluggable backend with
    an ABC, a factory and a config block. This is accessors over a dict the session store already
    persists; there is nothing to select between and nothing to configure.
    """

    _in_memory_warned = False

    @staticmethod
    def list(session: Session) -> List[PausedRun]:
        """
        Reads every paused run the session holds.

        The cache hands back Any, so entries are validated rather than trusted: one corrupted by
        application code is dropped with a warning instead of failing the resume of an intact one.

        :param session: The session to read from.
        :return: The valid records, in the order they were added.
        """
        stored = session.get_non_volatile_cache().get(AK_PAUSED_RUNS_KEY) or []
        if not isinstance(stored, list):
            _log.warning(f"Session '{session.id}': {AK_PAUSED_RUNS_KEY} is not a list; ignoring it.")
            return []

        records = []
        for entry in stored:
            try:
                records.append(entry if isinstance(entry, PausedRun) else PausedRun.model_validate(entry))
            except ValidationError as exc:
                _log.warning(f"Session '{session.id}': dropping an unreadable paused-run record. Error: {exc}")
        return records

    @staticmethod
    def get(session: Session, run_id: str) -> Optional[PausedRun]:
        """
        Finds one paused run by its id.

        :param session: The session to read from.
        :param run_id: The run id carried on the paused reply.
        :return: The record, or None when the session holds no run with that id.
        """
        return next((record for record in PausedRunState.list(session) if record.id == run_id), None)

    @staticmethod
    def find_by_interruption(session: Session, interruption_ids: Iterable[str]) -> Optional[PausedRun]:
        """
        Resolves which paused run a set of decisions belongs to.

        Interruption ids are unique across a session's records, so a resume that names no run id can
        still be routed. That is not a convenience: the AG-UI protocol has no field for a run id, so
        a resume arriving over that surface can only ever be identified this way.

        :param session: The session to read from.
        :param interruption_ids: The ids the decisions address.
        :return: The single record holding all of them, or None when they match none or span more
            than one — the caller reports that as a failed resume rather than guessing.
        """
        wanted = set(interruption_ids)
        if not wanted:
            return None

        matched = [record for record in PausedRunState.list(session) if wanted & {i.id for i in record.interruptions}]
        return matched[0] if len(matched) == 1 else None

    @staticmethod
    def add(session: Session, agent: str, interruptions: List[PausedInterruption], payload: Any = None) -> PausedRun:
        """
        Stores a new paused run and returns it, so the caller can read the assigned id back.

        Owns the three things every write needs, so each has one implementation: the generated run
        id, the picklability check, and the process-local-store warning.

        :param session: The session to write to.
        :param agent: The name of the agent that paused.
        :param interruptions: What the human has to decide.
        :param payload: The framework's opaque resume state.
        :return: The stored record, carrying its assigned id.
        :raises TypeError: If the payload cannot be pickled.
        :raises ValueError: If an interruption id repeats within this run, or is already used by
            another run in this session.
        """
        if not_picklable(payload):
            offender = first_unpicklable_entry(payload) if isinstance(payload, dict) else type(payload).__name__
            raise TypeError(
                f"Session '{session.id}' paused-run payload is not picklable; offending entry: {offender}. "
                f"The payload must be pickle-serializable so the session can be persisted."
            )

        incoming = [i.id for i in interruptions]
        repeated = sorted({i for i in incoming if incoming.count(i) > 1})
        if repeated:
            raise ValueError(
                f"Session '{session.id}' was given a paused run repeating interruption id(s): {', '.join(repeated)}. "
                f"Ids must be unique across a session's paused runs so a decision resolves to one run."
            )

        existing = PausedRunState.list(session)
        taken = {i.id for record in existing for i in record.interruptions}
        collisions = sorted(taken & set(incoming))
        if collisions:
            raise ValueError(
                f"Session '{session.id}' already holds a paused run using interruption id(s): {', '.join(collisions)}. "
                f"Ids must be unique across a session's paused runs so a decision resolves to one run."
            )

        record = PausedRun(
            id=uuid.uuid4().hex,
            agent=agent,
            created_at=datetime.now(timezone.utc).isoformat(),
            interruptions=interruptions,
            payload=payload,
        )
        session.get_non_volatile_cache().set(AK_PAUSED_RUNS_KEY, existing + [record])
        PausedRunState._warn_once_on_process_local_store(session)
        return record

    @staticmethod
    def clear(session: Session, run_id: str) -> None:
        """
        Removes one paused run. Silent when the session holds no run with that id.

        :param session: The session to write to.
        :param run_id: The run to remove.
        """
        remaining = [record for record in PausedRunState.list(session) if record.id != run_id]
        session.get_non_volatile_cache().set(AK_PAUSED_RUNS_KEY, remaining)

    @classmethod
    def _warn_once_on_process_local_store(cls, session: Session) -> None:
        """
        Warns the first time a pause is written against a process-local session store.

        Not a hard failure: a single-process development app pausing on the in-memory store is
        legitimate, and the capability has no enable flag, so there is no construction point at
        which a fail-fast could be scoped to apps that actually pause. Deliberately weaker than
        ScheduleManager's store-topology check, for that reason.

        :param session: The session being written to, named in the warning.
        """
        if cls._in_memory_warned:
            return
        try:
            session_type = AKConfig.get().session.type
        except Exception:
            return
        if session_type != "in_memory":
            return

        cls._in_memory_warned = True
        _log.warning(
            f"Session '{session.id}': a paused run was written while session.type is 'in_memory'. "
            "The record lives in this process only, so on a multi-replica deployment the replica "
            "receiving the human's decision will not find it. Configure a shared session backend "
            "(redis, valkey, dynamodb, cosmosdb or firestore) for durable pauses."
        )
