"""Request-handler Lambda: chat ingress plus custom scheduled-task management routes.

Unlike the ECS containerized target, the serverless target's router is not FastAPI — it is a
hand-rolled path/method table, so `ScheduleRESTRequestHandler` (a FastAPI APIRouter) cannot be
mounted here. Management is exposed instead through `Lambda.register` routes that call
`ScheduleManager` directly, which is the same object the REST handler wraps.

The routes match the containerized `ScheduleRESTRequestHandler`: the task id is the `{task_id}` path
parameter, read from `event["pathParameters"]`. These paths must also be declared in
`gateway_endpoints` in deploy/main.tf, with the same `{task_id}` name.

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


@Lambda.register("/schedules/{task_id}", method="GET")
def get_schedule(event, context):
    """GET /api/v1/schedules/{task_id} : read one of the caller's tasks."""
    task_id = event["pathParameters"]["task_id"]
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


@Lambda.register("/schedules/{task_id}", method="PUT")
def amend_schedule(event, context):
    """PUT /api/v1/schedules/{task_id} : full-replacement amendment of one of the caller's tasks.

    Body: {"prompt", "at"|"cron", "timezone", "session_mode", "status"}. Replaces the amendable
    state rather than merging, matching the containerized PUT route: an omitted occurrence field
    clears it.
    """
    task_id = event["pathParameters"]["task_id"]
    try:
        subject = _subject(event)
    except PermissionError as e:
        return 401, {"error": str(e)}
    try:
        task = _manager().update(task_id, json.loads(event.get("body") or "{}"), user_id=subject)
    except PermissionError as e:
        return 403, {"error": str(e)}
    except KeyError:
        return 404, {"error": f"Unknown scheduled task {task_id}"}
    except ValueError as e:
        return 400, {"error": str(e)}
    return task.model_dump(mode="json")


@Lambda.register("/schedules/{task_id}", method="DELETE")
def cancel_schedule(event, context):
    """DELETE /api/v1/schedules/{task_id} : cancel one of the caller's tasks.

    The record survives as the audit trail, so the cancelled task is returned.
    """
    task_id = event["pathParameters"]["task_id"]
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
