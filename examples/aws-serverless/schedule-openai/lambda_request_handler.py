"""Request-handler Lambda: chat ingress plus custom scheduled-task management routes.

Unlike the ECS containerized target, the serverless target's router is not FastAPI — it is a
hand-rolled path/method table, so `ScheduleRESTRequestHandler` (a FastAPI APIRouter) cannot be
mounted here. Management is exposed instead through `Lambda.register` routes that call
`ScheduleManager` directly, which is the same object the REST handler wraps.

Two consequences of the router being exact-match on the path:
  * no `{task_id}` path parameters: the task id travels as a query parameter or in the body
  * these paths must also be declared in `gateway_endpoints` in deploy/main.tf

The owner of a task is the caller the API Gateway authorizer (lambda_auth.py) authenticated: the
framework's chat route assigns that principal to the request body itself, and the custom routes read
it with `Lambda.principal(event)`. A client never names the owner.

Creation is deliberately absent here, exactly as in the REST handler: a task is created by the
`schedule` block on a chat request or by the agent's own `create_schedule` tool, so callers and
agents share one code path.
"""

import json

from agentkernel.aws import Lambda
from agentkernel.schedule import ScheduleManager


def _manager() -> ScheduleManager:
    """Resolve the process-wide manager, or fail loudly if the block is missing from config.yaml."""
    manager = ScheduleManager.get()
    if manager is None:
        raise ValueError("Scheduling is not configured. Add a 'schedule' block to config.yaml")
    return manager


def _subject(event) -> str:
    """The owner: the subject of the principal the authorizer established for this request.

    The authorizer denies a request without an accepted token before this Lambda runs, so an
    anonymous principal here means the API was deployed without the authorizer; refuse rather than
    read or change anybody's tasks.
    """
    principal = Lambda.principal(event)
    if principal.is_anonymous:
        raise PermissionError("Authentication required")
    return principal.subject


@Lambda.register("/schedules", method="GET")
def list_schedules(event, context):
    """GET /api/v1/schedules?limit=...&cursor=... : cursor-paginated listing of the caller's own tasks."""
    params = event.get("queryStringParameters") or {}
    try:
        page = _manager().list_tasks(
            user_id=_subject(event),
            limit=int(params["limit"]) if params.get("limit") else None,
            cursor=params.get("cursor"),
        )
    except PermissionError as e:
        return 401, {"error": str(e)}
    except ValueError as e:
        # A malformed `limit` or `cursor` is the caller's mistake, not a server fault.
        return 400, {"error": str(e)}
    return {
        "schedules": [task.model_dump(mode="json") for task in page.tasks],
        "next_cursor": page.next_cursor,
    }


@Lambda.register("/schedules/get", method="GET")
def get_schedule(event, context):
    """GET /api/v1/schedules/get?task_id=... : read one of the caller's tasks.

    A query parameter rather than a path segment: the serverless router matches paths exactly, so
    `/schedules/{task_id}` would never resolve.
    """
    params = event.get("queryStringParameters") or {}
    task_id = params.get("task_id")
    if not task_id:
        return 400, {"error": "task_id query parameter is required"}
    try:
        subject = _subject(event)
    except PermissionError as e:
        return 401, {"error": str(e)}
    try:
        task = _manager().get_task(task_id, user_id=subject)
    except PermissionError as e:
        return 403, {"error": str(e)}
    if task is None:
        return 404, {"error": f"Unknown scheduled task {task_id}"}
    return task.model_dump(mode="json")


@Lambda.register("/schedules/amend", method="POST")
def amend_schedule(event, context):
    """POST /api/v1/schedules/amend : full-replacement amendment of one of the caller's tasks.

    Body: {"task_id", "prompt", "at"|"cron", "timezone", "session_mode", "status"}.
    Replaces the amendable state rather than merging, matching the PUT route's semantics: an
    omitted occurrence field clears it.
    """
    body = json.loads(event.get("body") or "{}")
    task_id = body.pop("task_id", None)
    if not task_id:
        return 400, {"error": "task_id is required"}
    try:
        subject = _subject(event)
    except PermissionError as e:
        return 401, {"error": str(e)}
    try:
        task = _manager().update(task_id, body, user_id=subject)
    except PermissionError as e:
        return 403, {"error": str(e)}
    except KeyError:
        return 404, {"error": f"Unknown scheduled task {task_id}"}
    except ValueError as e:
        return 400, {"error": str(e)}
    return task.model_dump(mode="json")


@Lambda.register("/schedules/cancel", method="POST")
def cancel_schedule(event, context):
    """POST /api/v1/schedules/cancel : body {"task_id"}; cancels one of the caller's tasks.

    The record survives as the audit trail, so the cancelled task is returned.
    """
    body = json.loads(event.get("body") or "{}")
    task_id = body.get("task_id")
    if not task_id:
        return 400, {"error": "task_id is required"}
    try:
        subject = _subject(event)
    except PermissionError as e:
        return 401, {"error": str(e)}
    try:
        task = _manager().cancel(task_id, user_id=subject)
    except PermissionError as e:
        return 403, {"error": str(e)}
    except KeyError:
        return 404, {"error": f"Unknown scheduled task {task_id}"}
    except ValueError as e:
        return 400, {"error": str(e)}
    return task.model_dump(mode="json")


handler = Lambda.handler
