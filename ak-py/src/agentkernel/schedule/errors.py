"""Typed errors of the scheduling capability."""


class ScheduleError(Exception):
    """A schedule provider operation failed.

    Raised for failures of the backend that owns the timers (EventBridge Scheduler, the local
    scheduler thread) — registration, amendment, and deletion. Validation failures stay
    ``ValueError`` and ownership failures stay ``PermissionError``, so the REST handler and the
    agent tools can map each to its own surface behavior.
    """
