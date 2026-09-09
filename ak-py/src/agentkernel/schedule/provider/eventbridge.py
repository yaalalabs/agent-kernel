"""AWS EventBridge Scheduler trigger provider: one schedule per task, targeting the input queue.

The service owns the timers and interprets the occurrence rule itself, so this provider never
computes a fire time — it translates the spec into an EventBridge schedule expression, registers
the frozen trigger body as the target's static input, and lets AWS resolve the occurrence
placeholders through its context attributes at fire time.
"""

import datetime
import logging
import threading
from typing import Any, ClassVar, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

from ...core.config import _ScheduleProviderConfig
from ...core.util.factory import AKConfigError
from ..errors import ScheduleError
from ..model import TOKEN_OCCURRENCE_TIME, TOKEN_REQUEST_ID, ScheduledTask, ScheduleStatus
from ..timing import CRON_FIELD_COUNT
from .base import ScheduleProvider

# Context attributes EventBridge Scheduler resolves per occurrence, substituted into the frozen
# trigger body at registration time. The scheduled-time one is not optional decoration: an SQS FIFO
# target requires content-based deduplication (Scheduler cannot set a MessageDeduplicationId), so
# two occurrences of an otherwise identical body inside the dedup window would collapse into one.
CONTEXT_EXECUTION_ID = "<aws.scheduler.execution-id>"
CONTEXT_SCHEDULED_TIME = "<aws.scheduler.scheduled-time>"

# Name prefix of every schedule this provider registers, so AK's schedules are recognizable in a
# group that may hold others.
SCHEDULE_NAME_PREFIX = "ak-"

# One-time expression form; the spec's own timestamp is a local wall-clock time and the schedule's
# timezone is sent alongside it, so no offset belongs in this rendering.
AT_EXPRESSION_FORMAT = "%Y-%m-%dT%H:%M:%S"

# AWS reads "any day" as '?' rather than '*', and rejects a schedule that constrains both day
# fields at once.
CRON_ANY_DAY = "?"
CRON_EVERY = "*"

_NOT_FOUND_ERROR_CODE = "ResourceNotFoundException"


class EventBridgeScheduleProvider(ScheduleProvider):
    """Registers each task as an EventBridge Scheduler schedule delivering to an SQS queue.

    Durable and process-independent: the timers live in the service, so any process holding the
    same configuration can amend or cancel a task another one created. Delivery, however, is baked
    into the registration as an SQS target, which is why the provider declares SQS as its only
    supported transport.
    """

    supported_transports: ClassVar[Optional[frozenset[str]]] = frozenset({"sqs"})

    # Constructor settings that must come from the ``schedule.provider.eventbridge`` block. All
    # three are Terraform-provisioned, and without them a schedule cannot be registered at all.
    _REQUIRED_CONFIG_SETTINGS: ClassVar[Tuple[str, ...]] = ("group_name", "role_arn", "queue_arn")

    _log = logging.getLogger("ak.schedule.provider.eventbridge")

    def __init__(self, group_name: str, role_arn: str, queue_arn: str):
        """Initialize the provider.

        :param group_name: Schedule group the schedules are created in.
        :param role_arn: Execution role Scheduler assumes to deliver a trigger to the queue.
        :param queue_arn: Input queue the triggers are delivered to.
        """
        self._group_name = group_name
        self._role_arn = role_arn
        self._queue_arn = queue_arn
        self._client: Optional[Any] = None
        self._client_lock = threading.Lock()

    @classmethod
    def from_config(cls, provider_config: _ScheduleProviderConfig) -> "EventBridgeScheduleProvider":
        """Build the provider from its settings sub-block, rejecting an incomplete one.

        An incomplete block fails here rather than at the first deferral: a provider that cannot
        name its group, role and target queue can never register a schedule.

        :param provider_config: The ``schedule.provider`` block, carrying the ``eventbridge``
                                settings sub-block.
        :return: The configured provider.
        :raises AKConfigError: If the sub-block is absent, or any of its settings is missing.
        """
        eventbridge_config = provider_config.eventbridge
        if eventbridge_config is None or not (eventbridge_config.group_name and eventbridge_config.role_arn and eventbridge_config.queue_arn):
            missing = sorted(name for name in cls._REQUIRED_CONFIG_SETTINGS if not getattr(eventbridge_config, name, None))
            raise AKConfigError(
                f"schedule provider 'eventbridge' requires schedule.provider.eventbridge settings {missing}: "
                "they are provisioned by the AWS Terraform stack (AK_SCHEDULE__PROVIDER__EVENTBRIDGE__*)"
            )
        return cls(
            group_name=eventbridge_config.group_name,
            role_arn=eventbridge_config.role_arn,
            queue_arn=eventbridge_config.queue_arn,
        )

    def create(self, task: ScheduledTask, body_template: str) -> str:
        """Register the task as a schedule and return its ARN.

        :param task: The task to register.
        :param body_template: The frozen trigger body.
        :return: The schedule ARN, which is this provider's reference.
        :raises ScheduleError: If Scheduler rejected the registration.
        """
        self._log.info(f"Creating EventBridge schedule for scheduled task {task.task_id}")
        kwargs = self._schedule_kwargs(task, body_template, self._group_name, self._schedule_name(task.task_id))
        response = self._call("create_schedule", **kwargs)
        return response["ScheduleArn"]

    def update(self, task: ScheduledTask, body_template: str) -> None:
        """Replace the schedule's rule, body and enabled state.

        Scheduler has no partial update, so the whole registration — target included — is re-sent.

        :param task: The amended task.
        :param body_template: The re-frozen trigger body.
        :raises ScheduleError: If Scheduler rejected the amendment.
        """
        group_name, name = self._reference_parts(task.provider_ref, task.task_id)
        self._log.info(f"Updating EventBridge schedule {name} for scheduled task {task.task_id}")
        self._call("update_schedule", **self._schedule_kwargs(task, body_template, group_name, name))

    def delete(self, provider_ref: str) -> None:
        """Deregister a schedule, tolerating one that is already gone.

        A fired one-time schedule deletes itself (``ActionAfterCompletion``), so a cancellation
        arriving afterwards must still succeed.

        :param provider_ref: The schedule ARN returned by :meth:`create`.
        :raises ScheduleError: If Scheduler rejected the deletion for any other reason.
        """
        group_name, name = self._reference_parts(provider_ref)
        self._log.info(f"Deleting EventBridge schedule {name}")
        self._call("delete_schedule", tolerate_missing=True, Name=name, GroupName=group_name)

    def get(self, provider_ref: str) -> Optional[dict]:
        """Return Scheduler's own view of a schedule.

        :param provider_ref: The schedule ARN returned by :meth:`create`.
        :return: The native description, or None when the schedule no longer exists.
        """
        group_name, name = self._reference_parts(provider_ref)
        return self._call("get_schedule", tolerate_missing=True, Name=name, GroupName=group_name)

    def _schedule_kwargs(self, task: ScheduledTask, body_template: str, group_name: str, name: str) -> dict:
        """Build the create/update payload for a task.

        :param task: The task being registered.
        :param body_template: The frozen trigger body.
        :param group_name: Schedule group the registration lives in.
        :param name: Schedule name the registration lives under.
        :return: The keyword arguments for ``create_schedule``/``update_schedule``.
        :raises ValueError: If the occurrence rule cannot be expressed as an AWS schedule.
        """
        is_one_time = task.spec.at is not None
        return {
            "Name": name,
            "GroupName": group_name,
            "ScheduleExpression": self._schedule_expression(task),
            "ScheduleExpressionTimezone": task.spec.timezone,
            "FlexibleTimeWindow": {"Mode": "OFF"},
            # A fired one-time schedule has no further purpose; the store record is the audit trail.
            "ActionAfterCompletion": "DELETE" if is_one_time else "NONE",
            "State": "ENABLED" if task.status is ScheduleStatus.ACTIVE else "DISABLED",
            "Target": {
                "Arn": self._queue_arn,
                "RoleArn": self._role_arn,
                "Input": self._substitute_tokens(body_template),
                "SqsParameters": {"MessageGroupId": self.message_group_id(task)},
            },
        }

    @staticmethod
    def _schedule_name(task_id: str) -> str:
        """Return the schedule name a task is registered under."""
        return f"{SCHEDULE_NAME_PREFIX}{task_id}"

    @staticmethod
    def _substitute_tokens(body_template: str) -> str:
        """Point the occurrence placeholders at the context attributes AWS resolves at fire time.

        :param body_template: The frozen trigger body.
        :return: The body to register as the target's input.
        """
        return body_template.replace(TOKEN_REQUEST_ID, CONTEXT_EXECUTION_ID).replace(TOKEN_OCCURRENCE_TIME, CONTEXT_SCHEDULED_TIME)

    @classmethod
    def _schedule_expression(cls, task: ScheduledTask) -> str:
        """Render a task's occurrence rule as an EventBridge schedule expression.

        :param task: The task whose rule is being rendered.
        :return: An ``at(...)`` or ``cron(...)`` expression.
        :raises ValueError: If the rule cannot be expressed as an AWS schedule.
        """
        if task.spec.at is not None:
            return f"at({cls._at_timestamp(task.spec.at)})"
        return f"cron({cls._aws_cron_fields(task.spec.cron)})"

    @staticmethod
    def _at_timestamp(at: str) -> str:
        """Normalize a one-time timestamp to the second precision the ``at()`` form requires.

        The manager has already validated the timestamp, so this only reformats it.

        :param at: The spec's ISO-8601 local wall-clock timestamp.
        :return: The timestamp in the ``at()`` form.
        :raises ValueError: If the timestamp is not ISO-8601.
        """
        return datetime.datetime.fromisoformat(at).strftime(AT_EXPRESSION_FORMAT)

    @staticmethod
    def _aws_cron_fields(cron: str) -> str:
        """Translate a standard 5-field cron expression into the 6-field AWS flavor.

        AWS adds a trailing year field and requires exactly one of the two day fields to be the
        wildcard ``?``: constraining both day-of-month and day-of-week at once is rejected by the
        service, so it is rejected here where the caller still sees the error.

        :param cron: The standard 5-field expression.
        :return: The AWS field string (without the surrounding ``cron(...)``).
        :raises ValueError: If the expression is not 5 fields, or both day fields are constrained.
        """
        fields = cron.split()
        if len(fields) != CRON_FIELD_COUNT:
            raise ValueError(f"schedule 'cron' must be a standard {CRON_FIELD_COUNT}-field expression such as '0 9 * * 1': got '{cron}'")
        minute, hour, day_of_month, month, day_of_week = fields
        if day_of_month != CRON_EVERY and day_of_week != CRON_EVERY:
            raise ValueError(f"schedule 'cron' cannot constrain both the day-of-month and the day-of-week field: got '{cron}'")
        if day_of_week == CRON_EVERY:
            day_of_week = CRON_ANY_DAY
        else:
            day_of_month = CRON_ANY_DAY
        return f"{minute} {hour} {day_of_month} {month} {day_of_week} {CRON_EVERY}"

    def _reference_parts(self, provider_ref: Optional[str], task_id: Optional[str] = None) -> Tuple[str, str]:
        """Resolve the group and name a registration lives under from its stored reference.

        The reference is read rather than rebuilt from config so that renaming the configured group
        cannot orphan schedules that are already live under the old one. A reference that is not an
        ARN is treated as a bare name in the configured group.

        :param provider_ref: The stored provider reference (a schedule ARN).
        :param task_id: Task id to fall back to when no reference was stored yet.
        :return: A tuple of (group name, schedule name).
        :raises ScheduleError: If neither a reference nor a task id is available.
        """
        if provider_ref:
            # arn:aws:scheduler:<region>:<account>:schedule/<group>/<name>
            segments = provider_ref.rsplit("/", 2)
            if len(segments) == 3:
                return segments[1], segments[2]
            return self._group_name, segments[-1]
        if task_id:
            return self._group_name, self._schedule_name(task_id)
        raise ScheduleError("Cannot address an EventBridge schedule without a provider reference")

    def _call(self, operation: str, tolerate_missing: bool = False, **kwargs) -> Optional[dict]:
        """Invoke a Scheduler operation, mapping its failures onto ``ScheduleError``.

        :param operation: Name of the boto3 ``scheduler`` client method.
        :param tolerate_missing: Whether a missing schedule is an acceptable outcome (returns None).
        :param kwargs: Keyword arguments for the operation.
        :return: The AWS response, or None when a tolerated missing schedule was addressed.
        :raises ScheduleError: If Scheduler rejected the call.
        """
        try:
            return getattr(self._scheduler_client(), operation)(**kwargs)
        except ClientError as exc:
            error = exc.response.get("Error", {})
            if tolerate_missing and error.get("Code") == _NOT_FOUND_ERROR_CODE:
                self._log.debug(f"EventBridge schedule already absent for {operation}")
                return None
            raise ScheduleError(f"EventBridge Scheduler {operation} failed: {error.get('Message', exc)}") from exc

    def _scheduler_client(self):
        """Return the Scheduler client, creating it on first use.

        Deferred so that constructing the provider — which happens whenever the capability is
        configured — never reaches AWS; only an actual schedule operation does.
        """
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    self._client = boto3.client("scheduler")
        return self._client
