# AWS EventBridge Scheduler as a ScheduleProvider backend

Research notes backing the provider design in `../design.md`. All claims below were verified against
the AWS documentation on 2026-08-17 (sources at the bottom). EventBridge **Scheduler** (the
standalone `scheduler` API, `aws_scheduler_schedule` in Terraform) is the right service, not legacy
EventBridge **rules** (`aws_cloudwatch_event_rule`): rules have no one-time schedules, no per-schedule
IAM target role for SQS, and no auto-delete-after-completion.

## Capabilities that shape the design

- **Schedule expressions** (`ScheduleExpression`, verified in the CreateSchedule API reference):
  - `at(yyyy-mm-ddThh:mm:ss)`: one-time, fires once at the given wall-clock time.
  - `cron(minutes hours day_of_month month day_of_week year)`: recurring, six fields (AWS flavor, includes a year field).
  - `rate(value unit)`: recurring fixed interval (not needed by our design; cron covers the requirement).
  - `ScheduleExpressionTimezone`: optional IANA timezone the expression is evaluated in.
  - Takeaway: **one-time and recurring are different expression forms**, so the AK schedule model
    should carry them as distinct fields (`at` timestamp vs `cron` expression) rather than forcing
    one-time semantics onto a cron expression (a bare cron matches every year).
- **One-time lifecycle**: `ActionAfterCompletion: NONE | DELETE` (CreateSchedule API). With `DELETE`,
  Scheduler removes the schedule after the last invocation, so the provider does not need a cleanup
  job for fired one-time schedules. The AK task record in the ScheduleStore is what survives.
- **Start/end window**: `StartDate` / `EndDate` bound recurring schedules; both are ignored for
  one-time schedules. `State: ENABLED | DISABLED` allows pausing without deletion.
- **Schedule groups**: `GroupName` namespaces schedules (default group when omitted). A per-deployment
  group keeps AK-created schedules listable and IAM-scopable
  (`arn:aws:scheduler:REGION:ACCOUNT:schedule/GROUP/NAME`).
- **Create/update/delete surface**: `CreateSchedule`, `UpdateSchedule`, `GetSchedule`,
  `DeleteSchedule` map 1:1 onto the ScheduleProvider ABC. Errors are typed
  (`ConflictException` 409, `ResourceNotFoundException` 404, `ServiceQuotaExceededException` 402,
  `ThrottlingException` 429, `ValidationException` 400).

## SQS target constraints (the important ones)

Verified in the templated-targets guide and the `SqsParameters` API reference:

- The SQS templated target invokes `sqs:SendMessage` with:
  - `Target.Input`: the message **body** (a static string fixed at schedule creation; Scheduler
    context attributes such as `<aws.scheduler.schedule-arn>` and `<aws.scheduler.scheduled-time>`
    can be interpolated into it).
  - `SqsParameters.MessageGroupId`: the **only** SQS-specific parameter.
- **No SQS message attributes can be set.** Everything the consumer needs (request id, user id,
  schedule/task id) must travel in the message body. The AK input-queue consumer must therefore be
  able to process a scheduler-injected message whose metadata is body-embedded rather than
  attribute-carried.
- **No explicit `MessageDeduplicationId`.** "If you specify an Amazon SQS FIFO queue as a target,
  the queue must have content-based deduplication enabled" (SqsParameters reference). Since the
  body is static per schedule, two firings of the same recurring schedule inside one 5-minute
  dedup window would deduplicate to a single delivery; with `<aws.scheduler.scheduled-time>`
  interpolated into the body, occurrences differ and content-based dedup only collapses true
  duplicates. Cron's minimum granularity (1 minute) is inside the 5-minute window, so the
  interpolation is required, not optional, for schedules that fire more often than every 5 minutes.
- Optional delivery hardening (available, not required by the design): per-target `RetryPolicy`
  (`MaximumEventAgeInSeconds`, `MaximumRetryAttempts`) and `DeadLetterConfig` (SQS DLQ ARN).

## IAM model

Two distinct principals (verified in the templated-targets guide):

1. **The Scheduler execution role** (`Target.RoleArn`, required): assumed by the Scheduler service
   at fire time; needs `sqs:SendMessage` on the input queue. Trust policy principal:
   `scheduler.amazonaws.com`. Provisioned once by Terraform.
2. **The AK application role(s)** (ECS task role / Lambda execution role for whichever container
   creates schedules: request handler for chat-created schedules, agent runner for tool-created
   ones): need `scheduler:CreateSchedule`, `scheduler:UpdateSchedule`, `scheduler:DeleteSchedule`,
   `scheduler:GetSchedule` (scoped to the schedule group ARN) plus `iam:PassRole` on the execution
   role (Scheduler validates it can be passed at create/update time).

## Sources

- [CreateSchedule API reference](https://docs.aws.amazon.com/scheduler/latest/APIReference/API_CreateSchedule.html) (expressions, timezone, ActionAfterCompletion, State, GroupName, Start/EndDate, errors)
- [SqsParameters API reference](https://docs.aws.amazon.com/scheduler/latest/APIReference/API_SqsParameters.html) (MessageGroupId only; FIFO requires content-based dedup)
- [Using templated targets](https://docs.aws.amazon.com/scheduler/latest/UserGuide/managing-targets-templated.html) (SQS SendMessage example, execution-role permission policy, context attributes in Input)
