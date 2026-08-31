"""EventBridgeScheduleProvider: expression translation, registration payloads and error mapping.

The provider's whole job is to turn a task into one Scheduler API call, so the assertions are about
the exact kwargs AWS receives. boto3 is mocked at the module's own ``boto3.client`` attribute, the
idiom the SQS transport suite uses.
"""

import json

import pytest
from botocore.exceptions import ClientError

from agentkernel.core.config import AKConfig, _ScheduleConfig
from agentkernel.core.model import ScheduleSpec
from agentkernel.core.util.factory import AKConfigError
from agentkernel.schedule.errors import ScheduleError
from agentkernel.schedule.model import TOKEN_OCCURRENCE_TIME, TOKEN_REQUEST_ID, ScheduledTask, ScheduleStatus
from agentkernel.schedule.provider.base import _BUILTIN_SCHEDULE_PROVIDERS, ScheduleProviderFactory
from agentkernel.schedule.provider.eventbridge import (
    CONTEXT_EXECUTION_ID,
    CONTEXT_SCHEDULED_TIME,
    EventBridgeScheduleProvider,
)

GROUP_NAME = "ak-dev-schedules"
ROLE_ARN = "arn:aws:iam::123456789012:role/ak-dev-scheduler"
QUEUE_ARN = "arn:aws:sqs:us-east-1:123456789012:ak-dev-input.fifo"
SCHEDULE_ARN = f"arn:aws:scheduler:us-east-1:123456789012:schedule/{GROUP_NAME}/ak-t1"

BODY_TEMPLATE = json.dumps(
    {
        "prompt": "send the weekly report",
        "agent": "planner",
        "user_id": "u1",
        "session_id": "s1",
        "scheduled_task_id": "t1",
        "request_id": TOKEN_REQUEST_ID,
        "scheduled_time": TOKEN_OCCURRENCE_TIME,
    }
)


def _task(task_id: str = "t1", spec: ScheduleSpec = None, **overrides) -> ScheduledTask:
    fields = {
        "task_id": task_id,
        "user_id": "u1",
        "prompt": "send the weekly report",
        "agent": "planner",
        "session_id": "s1",
        "spec": spec or ScheduleSpec(cron="0 9 * * *"),
        "created_at": "2030-01-01T00:00:00+00:00",
        "updated_at": "2030-01-01T00:00:00+00:00",
    }
    fields.update(overrides)
    return ScheduledTask(**fields)


def _not_found(operation: str) -> ClientError:
    return ClientError({"Error": {"Code": "ResourceNotFoundException", "Message": "schedule not found"}}, operation)


class FakeSchedulerClient:
    """Records every Scheduler call and replays a configured response or failure."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.failures: dict[str, Exception] = {}

    def create_schedule(self, **kwargs):
        return self._record("create_schedule", kwargs, {"ScheduleArn": SCHEDULE_ARN})

    def update_schedule(self, **kwargs):
        return self._record("update_schedule", kwargs, {"ScheduleArn": SCHEDULE_ARN})

    def delete_schedule(self, **kwargs):
        return self._record("delete_schedule", kwargs, {})

    def get_schedule(self, **kwargs):
        return self._record("get_schedule", kwargs, {"Name": "ak-t1", "State": "ENABLED"})

    def _record(self, operation: str, kwargs: dict, response: dict):
        self.calls.append((operation, kwargs))
        failure = self.failures.get(operation)
        if failure is not None:
            raise failure
        return response

    def kwargs_of(self, operation: str) -> dict:
        return next(call_kwargs for name, call_kwargs in self.calls if name == operation)


@pytest.fixture
def client(monkeypatch) -> FakeSchedulerClient:
    fake = FakeSchedulerClient()
    monkeypatch.setattr("agentkernel.schedule.provider.eventbridge.boto3.client", lambda service, **kwargs: fake)
    return fake


@pytest.fixture
def provider() -> EventBridgeScheduleProvider:
    return EventBridgeScheduleProvider(group_name=GROUP_NAME, role_arn=ROLE_ARN, queue_arn=QUEUE_ARN)


class TestRegistration:
    def test_create_returns_the_schedule_arn_as_the_provider_reference(self, provider, client):
        assert provider.create(_task(), BODY_TEMPLATE) == SCHEDULE_ARN

    def test_create_sends_the_full_registration(self, provider, client):
        provider.create(_task(), BODY_TEMPLATE)

        kwargs = client.kwargs_of("create_schedule")
        assert kwargs["Name"] == "ak-t1"
        assert kwargs["GroupName"] == GROUP_NAME
        assert kwargs["ScheduleExpressionTimezone"] == "UTC"
        assert kwargs["FlexibleTimeWindow"] == {"Mode": "OFF"}
        assert kwargs["Target"]["Arn"] == QUEUE_ARN
        assert kwargs["Target"]["RoleArn"] == ROLE_ARN

    def test_the_target_input_points_at_the_occurrence_context_attributes(self, provider, client):
        provider.create(_task(), BODY_TEMPLATE)

        body = json.loads(client.kwargs_of("create_schedule")["Target"]["Input"])
        assert body["request_id"] == CONTEXT_EXECUTION_ID
        # The occurrence time keeps each body unique: an SQS FIFO target deduplicates on content.
        assert body["scheduled_time"] == CONTEXT_SCHEDULED_TIME
        assert "schedule" not in body

    def test_a_reused_session_groups_by_that_session(self, provider, client):
        provider.create(_task(), BODY_TEMPLATE)

        assert client.kwargs_of("create_schedule")["Target"]["SqsParameters"] == {"MessageGroupId": "s1"}

    def test_a_per_occurrence_session_groups_by_the_task(self, provider, client):
        provider.create(_task(spec=ScheduleSpec(cron="0 9 * * *", session_mode="new")), BODY_TEMPLATE)

        assert client.kwargs_of("create_schedule")["Target"]["SqsParameters"] == {"MessageGroupId": "t1"}

    def test_a_recurring_schedule_survives_its_occurrences(self, provider, client):
        provider.create(_task(), BODY_TEMPLATE)

        assert client.kwargs_of("create_schedule")["ActionAfterCompletion"] == "NONE"

    def test_a_one_time_schedule_deletes_itself_after_firing(self, provider, client):
        provider.create(_task(spec=ScheduleSpec(at="2030-06-01T09:00:00")), BODY_TEMPLATE)

        assert client.kwargs_of("create_schedule")["ActionAfterCompletion"] == "DELETE"

    def test_an_active_task_is_registered_enabled(self, provider, client):
        provider.create(_task(), BODY_TEMPLATE)

        assert client.kwargs_of("create_schedule")["State"] == "ENABLED"

    def test_a_paused_task_is_registered_disabled(self, provider, client):
        provider.create(_task(status=ScheduleStatus.PAUSED), BODY_TEMPLATE)

        assert client.kwargs_of("create_schedule")["State"] == "DISABLED"

    def test_the_spec_timezone_is_the_expression_timezone(self, provider, client):
        provider.create(_task(spec=ScheduleSpec(cron="0 9 * * *", timezone="Asia/Colombo")), BODY_TEMPLATE)

        assert client.kwargs_of("create_schedule")["ScheduleExpressionTimezone"] == "Asia/Colombo"


class TestScheduleExpressions:
    @staticmethod
    def _expression(provider, client, spec: ScheduleSpec) -> str:
        provider.create(_task(spec=spec), BODY_TEMPLATE)
        return client.kwargs_of("create_schedule")["ScheduleExpression"]

    def test_a_one_time_timestamp_becomes_an_at_expression(self, provider, client):
        assert self._expression(provider, client, ScheduleSpec(at="2030-06-01T09:00:00")) == "at(2030-06-01T09:00:00)"

    def test_a_timestamp_without_seconds_is_normalized(self, provider, client):
        assert self._expression(provider, client, ScheduleSpec(at="2030-06-01T09:00")) == "at(2030-06-01T09:00:00)"

    def test_an_unconstrained_cron_wildcards_the_day_of_week(self, provider, client):
        # AWS reads "any day" as '?', and requires exactly one of the two day fields to be it.
        assert self._expression(provider, client, ScheduleSpec(cron="0 9 * * *")) == "cron(0 9 * * ? *)"

    def test_a_day_of_month_cron_wildcards_the_day_of_week(self, provider, client):
        assert self._expression(provider, client, ScheduleSpec(cron="30 6 1 * *")) == "cron(30 6 1 * ? *)"

    def test_a_day_of_week_cron_wildcards_the_day_of_month(self, provider, client):
        assert self._expression(provider, client, ScheduleSpec(cron="0 9 * * 1")) == "cron(0 9 ? * 1 *)"

    def test_constraining_both_day_fields_is_rejected(self, provider, client):
        with pytest.raises(ValueError, match="cannot constrain both the day-of-month and the day-of-week"):
            self._expression(provider, client, ScheduleSpec(cron="0 9 1 * 1"))

    def test_a_malformed_cron_is_rejected(self, provider, client):
        with pytest.raises(ValueError, match="must be a standard 5-field expression"):
            self._expression(provider, client, ScheduleSpec(cron="0 9 *"))


class TestAmendmentAndRemoval:
    def test_update_re_sends_the_whole_registration(self, provider, client):
        task = _task(provider_ref=SCHEDULE_ARN, prompt="amended")

        provider.update(task, BODY_TEMPLATE)

        kwargs = client.kwargs_of("update_schedule")
        assert kwargs["Name"] == "ak-t1"
        assert kwargs["GroupName"] == GROUP_NAME
        # Scheduler has no partial update, so the target has to travel with every amendment.
        assert kwargs["Target"]["Arn"] == QUEUE_ARN
        assert kwargs["State"] == "ENABLED"

    def test_update_addresses_the_group_the_schedule_was_registered_in(self, provider, client):
        stale_group_ref = "arn:aws:scheduler:us-east-1:123456789012:schedule/ak-old-schedules/ak-t1"

        provider.update(_task(provider_ref=stale_group_ref), BODY_TEMPLATE)

        assert client.kwargs_of("update_schedule")["GroupName"] == "ak-old-schedules"

    def test_delete_deregisters_the_schedule(self, provider, client):
        provider.delete(SCHEDULE_ARN)

        assert client.kwargs_of("delete_schedule") == {"Name": "ak-t1", "GroupName": GROUP_NAME}

    def test_delete_tolerates_an_already_deleted_schedule(self, provider, client):
        # A fired one-time schedule removes itself, so a later cancellation must still succeed.
        client.failures["delete_schedule"] = _not_found("DeleteSchedule")

        assert provider.delete(SCHEDULE_ARN) is None

    def test_get_returns_the_native_description(self, provider, client):
        assert provider.get(SCHEDULE_ARN)["State"] == "ENABLED"

    def test_get_returns_none_for_a_schedule_that_is_gone(self, provider, client):
        client.failures["get_schedule"] = _not_found("GetSchedule")

        assert provider.get(SCHEDULE_ARN) is None

    def test_a_bare_reference_is_treated_as_a_name_in_the_configured_group(self, provider, client):
        provider.delete("ak-t1")

        assert client.kwargs_of("delete_schedule") == {"Name": "ak-t1", "GroupName": GROUP_NAME}


class TestErrorMapping:
    def test_a_rejected_registration_becomes_a_schedule_error(self, provider, client):
        client.failures["create_schedule"] = ClientError({"Error": {"Code": "ValidationException", "Message": "bad expression"}}, "CreateSchedule")

        with pytest.raises(ScheduleError, match="create_schedule failed: bad expression"):
            provider.create(_task(), BODY_TEMPLATE)

    def test_a_quota_failure_becomes_a_schedule_error(self, provider, client):
        client.failures["create_schedule"] = ClientError(
            {"Error": {"Code": "ServiceQuotaExceededException", "Message": "too many schedules"}}, "CreateSchedule"
        )

        with pytest.raises(ScheduleError, match="too many schedules"):
            provider.create(_task(), BODY_TEMPLATE)

    def test_a_missing_schedule_is_not_tolerated_on_update(self, provider, client):
        client.failures["update_schedule"] = _not_found("UpdateSchedule")

        with pytest.raises(ScheduleError, match="update_schedule failed: schedule not found"):
            provider.update(_task(provider_ref=SCHEDULE_ARN), BODY_TEMPLATE)


class TestFactoryWiring:
    @pytest.fixture(autouse=True)
    def _reset_config(self):
        AKConfig._reset()
        yield
        AKConfig._reset()

    @staticmethod
    def _configure(monkeypatch, **eventbridge_fields) -> None:
        schedule = _ScheduleConfig.model_validate({"provider": {"type": "eventbridge", "eventbridge": eventbridge_fields}})
        config = AKConfig.get().model_copy(update={"schedule": schedule})
        monkeypatch.setattr(AKConfig, "get", classmethod(lambda cls: config))

    def test_builds_the_provider_from_the_eventbridge_block(self, monkeypatch):
        self._configure(monkeypatch, group_name=GROUP_NAME, role_arn=ROLE_ARN, queue_arn=QUEUE_ARN)

        provider = ScheduleProviderFactory.create()

        assert isinstance(provider, EventBridgeScheduleProvider)
        assert provider._group_name == GROUP_NAME

    def test_an_incomplete_block_names_every_missing_setting(self, monkeypatch):
        self._configure(monkeypatch, group_name=GROUP_NAME)

        with pytest.raises(AKConfigError, match=r"requires schedule.provider.eventbridge settings \['queue_arn', 'role_arn'\]"):
            ScheduleProviderFactory.create()

    def test_a_missing_block_is_rejected(self, monkeypatch):
        schedule = _ScheduleConfig.model_validate({"provider": {"type": "eventbridge"}})
        config = AKConfig.get().model_copy(update={"schedule": schedule})
        monkeypatch.setattr(AKConfig, "get", classmethod(lambda cls: config))

        with pytest.raises(AKConfigError, match="requires schedule.provider.eventbridge settings"):
            ScheduleProviderFactory.create()

    def test_the_provider_declares_sqs_as_its_only_transport(self):
        # Delivery is baked into the registration as an SQS target, so the manager fails fast on
        # any other transport rather than registering a schedule that can never deliver.
        assert EventBridgeScheduleProvider.supported_transports == frozenset({"sqs"})

    def test_the_builtin_list_names_the_provider(self):
        assert _BUILTIN_SCHEDULE_PROVIDERS == ["local", "eventbridge"]
