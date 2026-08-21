"""Management REST routes of the scheduling capability.

Scheduled tasks are created by a chat request carrying a ``schedule`` block, or by an agent
through the ``create_schedule`` tool; this handler is the read-and-manage surface over them:
list, read, amend and cancel. It is the only module of the capability that imports FastAPI, so a
process that never serves HTTP never loads it.

Mount it beside a chat handler on any REST surface::

    RESTAPI.run(handlers=[AgentRESTRequestHandler(), ScheduleRESTRequestHandler(authoriser=...)])

Nothing mounts it implicitly: an app that wants the management surface passes it to the REST
entry point it already uses, exactly as it does for a Slack or thread handler. Mounting it also
validates the configured provider and store, so a broken pairing fails the app build.
"""

import logging
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..api.handler import AuthorisedRESTRequestHandler
from ..auth.authoriser import Authoriser
from .errors import ScheduleError
from .manager import ScheduleManager

# Reported when the capability is not configured. The routes are mounted either way on a surface
# that mounts this handler explicitly, so the caller is told the feature is off rather than that
# the path does not exist (the ThreadRESTRequestHandler convention).
_NOT_CONFIGURED_DETAIL = "Scheduling is not configured"

_NOT_OWNED_DETAIL = "Schedule is not owned by the authorised user"


class ScheduleAmendment(BaseModel):
    """Body of an amendment: the full amendable representation of a scheduled task.

    PUT semantics — an omitted occurrence field clears it rather than keeping the stored value,
    so the ``ScheduleSpec`` one-of rule (exactly one of ``at``/``cron``) applies to an amendment
    exactly as it does to a creation. ``status`` covers only the paused/active switch: completing
    and cancelling are lifecycle outcomes, not amendments.
    """

    prompt: str
    at: Optional[str] = None
    cron: Optional[str] = None
    timezone: str = "UTC"
    session_mode: Literal["reuse", "new"] = "reuse"
    status: Literal["active", "paused"] = "active"


class ScheduleRESTRequestHandler(AuthorisedRESTRequestHandler):
    """API router that exposes the scheduled-task management endpoints.

    Endpoints:
    - GET /api/v1/schedules: List scheduled tasks, most-recently updated first
    - GET /api/v1/schedules/{task_id}: Read one scheduled task
    - PUT /api/v1/schedules/{task_id}: Amend a task's occurrence rule, prompt or paused state
    - DELETE /api/v1/schedules/{task_id}: Cancel a task

    There is deliberately no create route: a task is created by a chat request carrying a
    ``schedule`` block, which keeps one creation path for callers and agents alike.

    When an Authoriser is supplied, every request must carry a Bearer token that the Authoriser
    resolves to a user_id (the inherited ``_resolve_user``); listings are scoped to that user and
    the single-task routes enforce ownership. Without an Authoriser, the routes are open.
    """

    def __init__(self, authoriser: Optional[Authoriser] = None):
        """Initializes a ScheduleRESTRequestHandler instance.

        :param authoriser: Optional user-supplied Authoriser protecting the schedule routes.
        """
        super().__init__(authoriser)
        self._log = logging.getLogger("ak.schedule.handler")

    def get_router(self) -> APIRouter:
        """
        Returns the APIRouter instance.

        Validates the scheduling configuration as the routes are mounted, so an unusable
        provider/store/transport pairing fails the app build rather than the first request.

        :raises AKConfigError: If the configured provider, store, or transport pairing is unusable.
        """
        ScheduleManager.validate_configuration()
        router = APIRouter()

        @router.get("/api/v1/schedules")
        def list_schedules(
            request: Request,
            user_id: Optional[str] = None,
            limit: Optional[int] = None,
            cursor: Optional[str] = None,
        ):
            manager = self._require_manager()
            resolved_user_id = self._resolve_user(request)
            if resolved_user_id is not None:
                user_id = resolved_user_id  # listings are forced to the authorised user
            try:
                page = manager.list_tasks(user_id=user_id, limit=limit, cursor=cursor)
            except (ValueError, ScheduleError) as e:
                raise self._as_http_error(e)
            return {
                "schedules": [task.model_dump(mode="json") for task in page.tasks],
                "next_cursor": page.next_cursor,
            }

        @router.get("/api/v1/schedules/{task_id}")
        def get_schedule(task_id: str, request: Request):
            manager = self._require_manager()
            resolved_user_id = self._resolve_user(request)
            try:
                task = manager.get_task(task_id, user_id=resolved_user_id)
            except PermissionError as e:
                raise self._as_http_error(e, task_id)
            if task is None:
                raise HTTPException(status_code=404, detail=f"Schedule {task_id} not found")
            return task.model_dump(mode="json")

        @router.put("/api/v1/schedules/{task_id}")
        def update_schedule(task_id: str, amendment: ScheduleAmendment, request: Request):
            manager = self._require_manager()
            resolved_user_id = self._resolve_user(request)
            try:
                task = manager.update(task_id, amendment.model_dump(), user_id=resolved_user_id)
            except (KeyError, PermissionError, ValueError, ScheduleError) as e:
                raise self._as_http_error(e, task_id)
            return task.model_dump(mode="json")

        @router.delete("/api/v1/schedules/{task_id}")
        def delete_schedule(task_id: str, request: Request):
            manager = self._require_manager()
            resolved_user_id = self._resolve_user(request)
            try:
                task = manager.cancel(task_id, user_id=resolved_user_id)
            except (KeyError, PermissionError, ValueError, ScheduleError) as e:
                raise self._as_http_error(e, task_id)
            return task.model_dump(mode="json")

        return router

    @staticmethod
    def _require_manager() -> ScheduleManager:
        """Return the shared manager, reporting a disabled capability to the caller.

        Resolved per request rather than at construction so an app can mount the routes without
        the capability being configured yet, exactly as the thread routes do.

        :return: The shared ScheduleManager.
        :raises HTTPException: 404 when the scheduling capability is not configured.
        """
        manager = ScheduleManager.get()
        if manager is None:
            raise HTTPException(status_code=404, detail=_NOT_CONFIGURED_DETAIL)
        return manager

    @staticmethod
    def _as_http_error(error: Exception, task_id: Optional[str] = None) -> HTTPException:
        """Map a manager error onto the HTTP status its surface reports.

        The manager's typed errors are the contract, so every route shares one mapping instead of
        interpreting each operation's failures itself.

        :param error: The error the manager raised.
        :param task_id: The task the request addressed, named in the not-found detail; omitted by
                        the listing route, which addresses no single task.
        :return: The HTTPException the route raises.
        """
        if isinstance(error, PermissionError):
            return HTTPException(status_code=403, detail=_NOT_OWNED_DETAIL)
        if isinstance(error, KeyError):
            return HTTPException(status_code=404, detail=f"Schedule {task_id} not found")
        if isinstance(error, ValueError):
            return HTTPException(status_code=400, detail=str(error))
        return HTTPException(status_code=500, detail=str(error))
