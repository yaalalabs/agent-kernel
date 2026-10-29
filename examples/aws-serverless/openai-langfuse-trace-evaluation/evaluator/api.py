import json
from typing import Any

import boto3

from .store import EvaluationStore


class EvaluationAPI:
    """The /eval and /check routes, and the grading that /eval starts in an asynchronous self-invocation."""

    START_GRADE = "START_GRADE"

    def __init__(self):
        self._store = EvaluationStore()
        self._lambda_client = boto3.client("lambda")

    def start_evaluation(self, event: dict, context: Any) -> tuple[int, dict]:
        """POST /eval: invokes this Lambda asynchronously with START_GRADE and returns right away."""
        session_id = json.loads(event.get("body") or "{}").get("session_id")
        if not session_id:
            return 400, {"error": "session_id is required"}
        # The judges run longer than API Gateway's 29 s, so they run in an asynchronous invocation of this Lambda
        self._lambda_client.invoke(
            FunctionName=context.function_name,
            InvocationType="Event",
            Payload=json.dumps({"action": self.START_GRADE, "session_id": session_id}),
        )
        return 202, {"session_id": session_id, "status": "grading started"}

    def check_results(self, event: dict, context: Any) -> tuple[int, dict]:
        """GET /check: returns the session's graded rows."""
        session_id = (event.get("queryStringParameters") or {}).get("session_id")
        if not session_id:
            return 400, {"error": "session_id is required"}
        rows = self._store.list_session_results(session_id)
        # DynamoDB returns numbers as Decimal, which json can't write
        return 200, {
            "session_id": session_id,
            "graded": len(rows),
            "results": json.loads(json.dumps(rows, default=float)),
        }

    @staticmethod
    def grade(event: dict) -> dict:
        """The START_GRADE invocation: grades the session's traces and stores the results."""
        from .grader import SessionGrader  # imported here so /chat, /eval and /check never load Opik

        return {"graded": SessionGrader().grade_session(event["session_id"])}
