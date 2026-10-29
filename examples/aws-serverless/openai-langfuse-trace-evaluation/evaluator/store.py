import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from agentkernel.test import AKEvaluationResult
from boto3.dynamodb.conditions import Key

from .case import TraceCase


class EvaluationStore:
    """One DynamoDB row per graded trace: its summary and one column per metric."""

    MAX_FIELD_CHARS = 4_096  # keeps a long answer or judge reason from bloating the row
    ROW_TTL = timedelta(days=90)
    SESSION_INDEX = "session_id-index"

    def __init__(self):
        self._table = boto3.resource("dynamodb").Table(os.environ["RESULTS_TABLE"])

    def save_results(self, case: TraceCase, results: list[AKEvaluationResult]) -> None:
        """Writes the trace's row with every metric's result."""
        now = datetime.now(timezone.utc)
        row = {
            "trace_id": case.trace_id,
            "session_id": case.session_id,
            "evaluated_at": now.isoformat(),
            "expires_at": int((now + self.ROW_TTL).timestamp()),
            "started_at": case.started_at.isoformat(),
            "latency_ms": case.latency_ms,
            "input": self._truncate(case.user_input),
            "output": self._truncate(case.output),
            "agents": case.agents,
            "tool_calls": [
                self._to_dynamodb_attributes(
                    {
                        "name": call.name,
                        "input": self._truncate(call.input),
                        "output": self._truncate(call.output),
                        "failed": call.failed,
                    }
                )
                for call in case.tool_calls
            ],
            "input_tokens": case.usage.input_tokens,
            "output_tokens": case.usage.output_tokens,
            "total_tokens": case.usage.total_tokens,
            "cost": case.usage.cost,
            "passed": all(result.passed for result in results),
        }
        for result in results:
            row[result.metric] = self._to_dynamodb_attributes(
                {
                    "score": result.score,
                    "threshold": result.threshold,
                    "passed": result.passed,
                    "reason": self._truncate(result.reason),
                    "higher_is_better": result.metadata.get("higher_is_better"),
                }
            )
        self._table.put_item(Item=self._to_dynamodb_attributes(row))

    def list_session_results(self, session_id: str) -> list[dict]:
        """Returns the session's rows (a demo session has a handful, so one query page is enough)."""
        response = self._table.query(
            IndexName=self.SESSION_INDEX, KeyConditionExpression=Key("session_id").eq(session_id)
        )
        return response["Items"]

    @classmethod
    def _to_dynamodb_attributes(cls, attributes: dict) -> dict:
        """Drops None values (boto3 would store DynamoDB NULLs) and turns numbers into the Decimals boto3 requires."""
        return {
            name: Decimal(str(value)) if isinstance(value, (int, float)) and not isinstance(value, bool) else value
            for name, value in attributes.items()
            if value is not None
        }

    @classmethod
    def _truncate(cls, text: str | None) -> str | None:
        """Cuts text longer than MAX_FIELD_CHARS."""
        if text is None or len(text) <= cls.MAX_FIELD_CHARS:
            return text
        return text[: cls.MAX_FIELD_CHARS] + "…[truncated]"
