import gzip
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any

import boto3
from agentkernel.test import AKEvaluationResult
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from pydantic import BaseModel

from .case import TraceCase

_log = logging.getLogger("ak.example.trace_evaluation")


class Progress(StrEnum):
    PENDING = "pending"  # finished, not ready yet
    GRADING = "grading"  # ready and queued for the judges
    GRADED = "graded"  # every metric judged and stored; final
    FAILED = "failed"  # grading raised; error recorded; retried by the next /eval
    UNFINISHED = "unfinished"  # root span has no output; final, never graded


class TraceProgress(BaseModel):
    progress: Progress
    updated_at: datetime


class SessionProgress(BaseModel):
    counts: dict[Progress, int] = {}
    errors: list[dict[str, str]] = []  # {"trace_id", "error"} per failed row


class EvaluationStore:
    """One DynamoDB row per trace: its progress, its summary and, once graded, one column per metric."""

    MAX_FIELD_CHARS = 4_096  # characters per input/output/reason field
    MAX_STORED_TOOL_CALLS = 25  # tool calls stored on the trace row
    MAX_ITEM_BYTES = 380_000  # DynamoDB's 400 KB item cap minus headroom
    ROW_TTL = timedelta(days=90)
    SESSION_INDEX = "session_id-index"
    TRUNCATION_MARKER = "…[truncated]"
    _BATCH_GET_MAX_KEYS = 100  # BatchGetItem's key limit
    _BATCH_GET_RETRY_WAITS = (0.5, 1.0, 2.0)
    _NUMBER_BYTES = 21  # DynamoDB's documented upper bound for a number

    def __init__(self, table: Any):
        self._table = table

    @classmethod
    def for_table(cls, table_name: str) -> "EvaluationStore":
        """Builds a store on the named DynamoDB table."""
        return cls(boto3.resource("dynamodb").Table(table_name))

    def read_progress(self, trace_ids: list[str]) -> dict[str, TraceProgress]:
        """Each trace's current progress, read strongly consistent; traces with no row are absent."""
        progress_by_id: dict[str, TraceProgress] = {}
        unique_ids = list(dict.fromkeys(trace_ids))
        for start in range(0, len(unique_ids), self._BATCH_GET_MAX_KEYS):
            batch_ids = unique_ids[start : start + self._BATCH_GET_MAX_KEYS]
            request = {
                self._table.name: {
                    "Keys": [{"trace_id": trace_id} for trace_id in batch_ids],
                    "ConsistentRead": True,
                    "ProjectionExpression": "#t, #p, #u",
                    "ExpressionAttributeNames": {"#t": "trace_id", "#p": "progress", "#u": "updated_at"},
                }
            }
            for item in self._batch_get_with_retries(request):
                progress_by_id[item["trace_id"]] = TraceProgress(
                    progress=item["progress"], updated_at=item["updated_at"]
                )
        return progress_by_id

    def write_progress(
        self, case: TraceCase, progress: Progress, now: datetime, lease_expired_before: datetime
    ) -> bool:
        """Writes the trace's summary row with ``progress``; returns False when the row may not be overwritten.

        Only a new row, a pending or failed one, or a grading one whose lease began before ``lease_expired_before``
        is overwritten, atomically: graded and unfinished rows stay final, and only one /eval claims a trace.
        """
        try:
            self._table.put_item(
                Item=self._shrink_to_item_limit(self._build_trace_row(case, progress, now)),
                ConditionExpression=(
                    "attribute_not_exists(trace_id) OR #p IN (:pending, :failed) OR (#p = :grading AND #u < :expired)"
                ),
                ExpressionAttributeNames={"#p": "progress", "#u": "updated_at"},
                ExpressionAttributeValues={
                    ":pending": Progress.PENDING.value,
                    ":failed": Progress.FAILED.value,
                    ":grading": Progress.GRADING.value,
                    ":expired": self._to_utc_iso(lease_expired_before),
                },
            )
        except ClientError as e:
            if not self._is_condition_check_failure(e):
                raise
            _log.info(f"trace {case.trace_id} is final or claimed by another /eval; left as is")
            return False
        return True

    def save_results(self, case: TraceCase, results: list[AKEvaluationResult], now: datetime) -> None:
        """Writes the whole graded row in one PutItem, so every metric column lands at once."""
        row = self._build_trace_row(case, Progress.GRADED, now)
        row["evaluated_at"] = row["updated_at"]
        scored_results = [result for result in results if result.score is not None]
        if scored_results:
            row["passed"] = all(result.passed for result in scored_results)
        row["metric_errors"] = len(results) - len(scored_results)
        for result in results:
            row[result.metric] = self._build_metric_column(result)
        row = self._shrink_to_item_limit(row)

        spans_gz = gzip.compress(json.dumps([span.model_dump(mode="json") for span in case.spans]).encode())
        if self._item_bytes(row) + len("spans_gz") + len(spans_gz) <= self.MAX_ITEM_BYTES:
            row["spans_gz"] = spans_gz
        else:
            row["spans_truncated"] = True
        self._table.put_item(Item=row)

    def mark_failed(self, trace_ids: list[str], error: str, now: datetime) -> None:
        """Marks rows that are still grading as failed, with the error."""
        for trace_id in trace_ids:
            try:
                self._table.update_item(
                    Key={"trace_id": trace_id},
                    UpdateExpression="SET #p = :failed, #e = :error, #u = :now",
                    ConditionExpression="#p = :grading",
                    ExpressionAttributeNames={"#p": "progress", "#e": "error", "#u": "updated_at"},
                    ExpressionAttributeValues={
                        ":failed": Progress.FAILED.value,
                        ":grading": Progress.GRADING.value,
                        ":error": self._truncate(error),
                        ":now": self._to_utc_iso(now),
                    },
                )
            except ClientError as e:
                if not self._is_condition_check_failure(e):
                    raise
                _log.info(f"trace {trace_id} is no longer grading; not marked failed")

    def count_session_progress(self, session_id: str) -> SessionProgress:
        """Counts a session's rows by progress, from the eventually consistent session index."""
        session_progress = SessionProgress()
        query_args: dict[str, Any] = {
            "IndexName": self.SESSION_INDEX,
            "KeyConditionExpression": Key("session_id").eq(session_id),
            "ProjectionExpression": "#t, #p, #e",
            "ExpressionAttributeNames": {"#t": "trace_id", "#p": "progress", "#e": "error"},
        }
        while True:
            response = self._table.query(**query_args)
            for item in response.get("Items", []):
                try:
                    progress = Progress(item.get("progress"))
                except ValueError:
                    _log.warning(f"trace {item.get('trace_id')} has unknown progress {item.get('progress')!r}; skipped")
                    continue
                session_progress.counts[progress] = session_progress.counts.get(progress, 0) + 1
                if progress == Progress.FAILED:
                    session_progress.errors.append({"trace_id": item["trace_id"], "error": item.get("error", "")})
            if "LastEvaluatedKey" not in response:
                return session_progress
            query_args["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    def _batch_get_with_retries(self, request: dict) -> list[dict]:
        """Runs a BatchGetItem, retrying the keys DynamoDB leaves unprocessed."""
        items: list[dict] = []
        for wait in (*self._BATCH_GET_RETRY_WAITS, None):
            response = self._table.meta.client.batch_get_item(RequestItems=request)
            items.extend(response.get("Responses", {}).get(self._table.name, []))
            request = response.get("UnprocessedKeys") or {}
            if not request:
                return items
            if wait is None:
                break
            time.sleep(wait)
        raise RuntimeError(f"DynamoDB left keys unprocessed after {len(self._BATCH_GET_RETRY_WAITS)} retries")

    def _build_trace_row(self, case: TraceCase, progress: Progress, now: datetime) -> dict:
        """Builds the trace's row without metric columns: its progress, request, answer, tool calls and usage."""
        stored_tool_calls = case.tool_calls[: self.MAX_STORED_TOOL_CALLS]
        row = {
            "trace_id": case.trace_id,
            "session_id": case.session_id,
            "progress": progress.value,
            "updated_at": self._to_utc_iso(now),
            "expires_at": int((now + self.ROW_TTL).timestamp()),
            "provider": case.provider,
            "root_name": case.root_name,
            "started_at": self._to_utc_iso(case.started_at),
            "latency_ms": case.latency_ms,
            "input": self._truncate(case.user_input),
            "output": self._truncate(case.output),
            "tool_calls": [
                self._to_dynamodb_attributes(
                    {
                        "name": call.name,
                        "input": self._truncate(call.input),
                        "output": self._truncate(call.output),
                        "failed": call.failed,
                    }
                )
                for call in stored_tool_calls
            ],
            "tool_call_count": len(case.tool_calls),
            "tool_error_count": sum(1 for call in case.tool_calls if call.failed),
            "agents": case.agents,
            "span_count": case.span_count,
            "input_tokens": case.usage.input_tokens,
            "output_tokens": case.usage.output_tokens,
            "total_tokens": case.usage.total_tokens,
            "cost": case.usage.cost,
        }
        if len(stored_tool_calls) < len(case.tool_calls):
            row["tool_calls_truncated"] = True
        return self._to_dynamodb_attributes(row)

    def _build_metric_column(self, result: AKEvaluationResult) -> dict:
        """Builds one metric's column: a map of its score, threshold, verdict and the judge's reason."""
        return self._to_dynamodb_attributes(
            {
                "evaluator": result.evaluator,
                "score": result.score,
                "threshold": result.threshold,
                "passed": result.passed,
                "reason": self._truncate(result.reason),
                "higher_is_better": result.metadata.get("higher_is_better"),
                "attempts": result.metadata.get("attempts"),
            }
        )

    def _shrink_to_item_limit(self, row: dict) -> dict:
        """Drops tool calls from the end, then halves input and output, until the row fits MAX_ITEM_BYTES."""
        while self._item_bytes(row) > self.MAX_ITEM_BYTES:
            if row.get("tool_calls"):
                row["tool_calls"].pop()
                row["tool_calls_truncated"] = True
                continue
            shortened = False
            for field in ("input", "output"):
                text = row.get(field, "").removesuffix(self.TRUNCATION_MARKER)
                if text:
                    row[field] = text[: len(text) // 2] + self.TRUNCATION_MARKER
                    shortened = True
            if not shortened:
                break  # only metric columns left; four truncated reasons stay well under the limit
        return row

    @classmethod
    def _to_dynamodb_attributes(cls, attributes: dict) -> dict:
        """Drops None values (boto3 would store DynamoDB NULLs) and turns numbers into Decimals."""
        return {
            name: cls._to_decimal(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else value
            for name, value in attributes.items()
            if value is not None
        }

    @staticmethod
    def _to_decimal(value: float | int | None) -> Decimal | None:
        """Converts a number to the Decimal boto3 requires for DynamoDB numbers."""
        return None if value is None else Decimal(str(value))

    @classmethod
    def _truncate(cls, text: str | None) -> str | None:
        """Cuts text longer than MAX_FIELD_CHARS and appends TRUNCATION_MARKER."""
        if text is None or len(text) <= cls.MAX_FIELD_CHARS:
            return text
        return text[: cls.MAX_FIELD_CHARS] + cls.TRUNCATION_MARKER

    @staticmethod
    def _to_utc_iso(value: datetime) -> str:
        """Formats a datetime as an ISO 8601 string in UTC, always with microseconds so strings sort by time."""
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")

    @classmethod
    def _item_bytes(cls, row: dict) -> int:
        """Estimates a whole item's size the way DynamoDB counts it: names, values, and list/map overhead."""
        return sum(len(name.encode()) + cls._attribute_bytes(value) for name, value in row.items())

    @classmethod
    def _attribute_bytes(cls, value: Any) -> int:
        """Estimates one attribute value's size the way DynamoDB counts it."""
        if isinstance(value, str):
            return len(value.encode())
        if isinstance(value, (bytes, bytearray)):
            return len(value)
        if isinstance(value, bool) or value is None:
            return 1
        if isinstance(value, (int, float, Decimal)):
            return cls._NUMBER_BYTES
        if isinstance(value, dict):
            return 3 + sum(1 + len(name.encode()) + cls._attribute_bytes(nested) for name, nested in value.items())
        if isinstance(value, (list, tuple)):
            return 3 + sum(1 + cls._attribute_bytes(element) for element in value)
        return len(str(value).encode())

    @staticmethod
    def _is_condition_check_failure(error: ClientError) -> bool:
        """True when a conditional write was rejected because its condition did not hold."""
        return error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"
