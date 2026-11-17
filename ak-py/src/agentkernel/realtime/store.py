import asyncio
import logging
from collections.abc import Callable

from ..core.base import Session
from ..core.runtime import Runtime
from ..core.session.serde import BinarySerde


class RealtimeTurnStore:
    """Saves one realtime call's session: after each finished turn, and once more when the call ends.

    A call runs for minutes and the session store only sees a ``Runtime.run()``, so without this a call that
    failed late would lose every turn it had. Built by ``RealtimeConnection``, one per call, and used on the pool
    loop only.

    Semantics, in order:

    1. ``save_turn()`` runs when a turn ends. It pickles the session on the pool loop, where every change to the
       session happens, so ADK or a hook cannot change it mid-copy. It does nothing for a failed call or a call
       that has started closing.
    2. The pickled copy waits in ``_pending_turn``. A turn still waiting is replaced by a newer one, so a slow
       store never builds a backlog. One writer task (``_turn_writer``) drains it.
    3. Each write rebuilds the session from the copy and stores it on a worker thread: every call in the process
       shares the pool loop, and a store can be several network round trips.
    4. Every write of the call, a turn's or the final one, runs under ``_store_lock``: one at a time, in the order
       they were made.
    5. ``wait_for_turns()`` lets the writer finish; the connection calls it at close, then ``store_final()``
       writes the live session. This happens only after the runner has disconnected, because ADK writes its own
       data while disconnecting.
    6. ``mark_failed()`` stops all further saving: a halted or half-finished turn is never stored, and the next
       call starts from the last finished turn.
    7. A failed write is logged, never raised, so the call still ends.
    """

    _log = logging.getLogger("ak.realtime.store")

    def __init__(self, session_id: str, runtime: Runtime, session: Session, is_closing: Callable[[], bool]):
        """
        :param session_id: The AK session id, for log lines.
        :param runtime: The runtime whose session store is written.
        :param session: The call's live session.
        :param is_closing: True once the call has started closing; no turn is saved after that.
        """
        self.session_id = session_id
        self.runtime = runtime
        self.session = session
        self._is_closing = is_closing
        # The call failed (a native error, a halt, a failed connect): its session is not stored again, so the last
        # finished turn is what the next call starts from.
        self.failed = False
        # The newest finished turn's pickled session still waiting to be written (an older waiting one is replaced),
        # the task writing turns, and the lock that keeps every write of this call one at a time.
        self._pending_turn: dict[str, bytes] | None = None
        self._turn_writer: asyncio.Task | None = None
        self._store_lock = asyncio.Lock()

    def mark_failed(self) -> None:
        """Stop saving: the call failed, so its session is not stored again."""
        self.failed = True

    def save_turn(self) -> None:
        """Store the session as it stands after a finished turn, so a call that fails later loses only the turn in progress.

        Only the pickling happens here, on the pool loop where every change to the session happens, so ADK or a hook
        cannot change the session mid-copy. Unpickling and the write run on a worker thread. A slow store never
        builds a backlog: a turn still waiting is replaced by the newer one. A halted turn never gets here (the halt
        fails the call first), and a failed call stores nothing more.
        """
        if self.failed or self._is_closing():
            return
        try:
            snapshot = {key: BinarySerde.dumps(value) for key, value in self.session.get_all(volatile=False)}
        except Exception:
            self._log.exception(f"Realtime session {self.session_id}: copying the session at the end of a turn failed")
            return
        self._pending_turn = snapshot
        if self._turn_writer is None or self._turn_writer.done():
            self._turn_writer = asyncio.create_task(self._write_turns())

    async def wait_for_turns(self) -> None:
        """Wait for the turn writer to finish what it has; a write that failed was already logged."""
        if self._turn_writer is not None:
            await asyncio.gather(self._turn_writer, return_exceptions=True)

    async def store_final(self) -> None:
        """Store the live session once the call has ended normally."""
        await self._store_final(self.session)

    async def _write_turns(self) -> None:
        """Write the waiting turn copy, and any newer one that arrives meanwhile, until none is left."""
        while self._pending_turn is not None:
            snapshot, self._pending_turn = self._pending_turn, None
            await self._store_turn(snapshot)

    def _rebuild(self, snapshot: dict[str, bytes]) -> Session:
        """Build the session a turn copy stands for. Runs on the worker thread: nothing else holds this object."""
        session = Session(self.session.id)
        for key, payload in snapshot.items():
            session.set(key, BinarySerde.loads(payload))
        return session

    async def _store_turn(self, snapshot: dict[str, bytes]) -> None:
        """Store a finished turn's pickled copy of the session: rebuild it on a worker thread and write it.

        :param snapshot: The pickled session keys, as ``save_turn`` copied them.
        """
        await self._write(lambda: self.runtime.sessions().store(self._rebuild(snapshot)))

    async def _store_final(self, session: Session) -> None:
        """Store the live session once the call has ended normally.

        :param session: The call's session.
        """
        await self._write(lambda: self.runtime.sessions().store(session))

    async def _write(self, store_call) -> None:
        """Run one store write on a worker thread, under the lock that keeps this call's writes one at a time.

        Every call in the process shares the pool loop, and a store can be several network round trips, so the write
        never runs on it. Writes run in the order they were made. A failure is logged, never raised, so the run
        still ends.

        :param store_call: The blocking store call.
        """
        async with self._store_lock:
            try:
                await asyncio.to_thread(store_call)
                self._log.debug(f"Realtime session {self.session_id}: session stored")
            except Exception:
                self._log.exception(f"Realtime session {self.session_id}: storing the session failed")
