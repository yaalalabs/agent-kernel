import json
import logging
import os
from typing import Any, Callable

import boto3

from .job import TraceEvaluationJob
from .store import EvaluationStore, Progress

_log = logging.getLogger("ak.example.trace_evaluation")


class EvaluationAPI:
    """The /eval, /check and /grade routes the request handler registers with Lambda.register.

    /grade is internal: /eval invokes the Lambda itself asynchronously with a /grade request, and the path is
    not in the API Gateway's endpoints, so it can't be called from outside.
    """

    GRADE_ROUTE = "grade"
    MAX_ERRORS_SHOWN = 10

    def __init__(self, store: EvaluationStore, lambda_client: Any, job_factory: Callable[[], TraceEvaluationJob]):
        self._store = store
        self._lambda_client = lambda_client
        self._job_factory = job_factory
        self._job: TraceEvaluationJob | None = None

    @classmethod
    def from_env(cls) -> "EvaluationAPI":
        """Builds the API on the RESULTS_TABLE table and a Lambda client."""
        # Nothing heavy here: Trace.get() and the Opik metrics are built on first use, so /chat cold starts skip them
        return cls(
            EvaluationStore.for_table(os.environ["RESULTS_TABLE"]),
            boto3.client("lambda"),
            TraceEvaluationJob.from_env,
        )

    def start_evaluation(self, event: dict, context: Any) -> tuple[int, dict]:
        """POST /eval: prepares the session's traces and starts grading the ready ones asynchronously."""
        try:
            body = json.loads(event.get("body") or "{}")
        except ValueError:
            return 400, {"error": "request body is not valid JSON"}
        session_id = body.get("session_id") if isinstance(body, dict) else None
        if not isinstance(session_id, str) or not session_id:
            return 400, {"error": "session_id is required"}

        summary = self._get_job().prepare_traces(session_id)
        if summary.grading_ids:
            # The judges run in an asynchronous invocation of this Lambda, bound by its timeout rather than
            # API Gateway's 29 s. It is a POST /grade request next to this /eval one, so Lambda.handler routes it.
            grade_request = {
                "httpMethod": "POST",
                "path": event.get("path", "").removesuffix("eval") + self.GRADE_ROUTE,
                "body": json.dumps({"session_id": session_id, "trace_ids": summary.grading_ids}),
            }
            self._lambda_client.invoke(
                FunctionName=context.function_name, InvocationType="Event", Payload=json.dumps(grade_request)
            )
        return 202, summary.model_dump(mode="json")

    def check_progress(self, event: dict, context: Any) -> tuple[int, dict]:
        """GET /check: counts the session's traces by progress; complete once ``expected`` are graded."""
        params = event.get("queryStringParameters") or {}
        session_id = params.get("session_id")
        if not session_id:
            return 400, {"error": "session_id is required"}
        try:
            expected = int(params.get("expected", ""))
        except ValueError:
            expected = 0
        if expected < 1:
            return 400, {"error": "expected must be a positive integer"}

        session_progress = self._store.count_session_progress(session_id)
        counts = {state.value: session_progress.counts.get(state, 0) for state in Progress}
        return 200, {
            "session_id": session_id,
            "expected": expected,
            **counts,
            "errors": session_progress.errors[: self.MAX_ERRORS_SHOWN],
            # >=, not ==: a retried chat request can leave one trace more than the requests counted
            "complete": counts[Progress.GRADED.value] >= expected,
        }

    def grade_traces(self, event: dict, context: Any) -> tuple[int, dict]:
        """POST /grade (internal): judges the traces /eval marked grading."""
        body = json.loads(event["body"])
        return 200, self._get_job().grade_traces(body["session_id"], body["trace_ids"]).model_dump(mode="json")

    def _get_job(self) -> TraceEvaluationJob:
        """Builds the job on first use, so /chat cold starts never build the tracer client."""
        if self._job is None:
            self._job = self._job_factory()
        return self._job
