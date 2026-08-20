# Agent Kernel Scheduled & Recurring Chats on AWS ECS

This package demonstrates the Agent Kernel **scheduling capability** deployed on AWS ECS: a chat
request carrying a `schedule` block is not run — it is registered as a scheduled task and
acknowledged with **HTTP 202**. When an occurrence is due, AWS EventBridge Scheduler delivers the
stored prompt into the Input Queue as a plain chat request, and the agent runner executes it
through the normal path.

Nothing in `app_agent_runner.py` mentions scheduling. The `schedule` block in `config.yaml` is the
whole switch.

## Architecture Overview

- **REST Service ECS Task** — three roles in one service: chat ingress (enqueue + poll the response
  store), the output-queue consumer thread, and the **schedule management routes**
  (`/api/v1/schedules`).
- **Agent Runner ECS Task** — consumes the Input Queue. It runs fired occurrences *and* registers
  new tasks, whether the request carried a `schedule` block or the agent called `create_schedule`
  itself.
- **EventBridge Scheduler** — owns the timers. One schedule per task, named `ak-<task_id>`, inside a
  schedule group Terraform provisions, targeting the Input Queue.
- **DynamoDB** — three tables: session store, response store, and the **schedule store** holding the
  task records.
- **SQS FIFO queues** — the Input Queue is the delivery target for both the REST service and
  Scheduler.

```
POST /api/v1/chat  {"schedule": {...}}          POST /api/v1/chat  (no schedule)
        |                                               |
   REST Service ---> Input Queue ---> Agent Runner ---> Output Queue ---> REST Service
        |                  ^               |
        |                  |               +--> registers ak-<task_id> in the schedule group
        |                  |                    and writes the record to the schedule store
        |            EventBridge Scheduler
        |            (fires each occurrence)
        |
   GET/PUT/DELETE /api/v1/schedules --> schedule store + Scheduler (direct, no queue round trip)
```

## Deployed Resources

- **ECS Services**: REST Service (FastAPI + output-queue poller) and Agent Runner
- **SQS**: FIFO input and output queues, with DLQs. The input queue runs with **content-based
  deduplication** — see [Why the input queue changes](#why-the-input-queue-changes) below
- **EventBridge Scheduler**: a schedule group plus the execution role Scheduler assumes to send to
  the input queue
- **DynamoDB**: session store, response store, schedule store (partition `task_id`, no sort key)
- **IAM**: `scheduler:{Create,Update,Delete,Get}Schedule` + `iam:PassRole` on both task roles
- **API Gateway + ALB**: HTTP API with VPC Link, routing the chat route and the schedule routes
- **VPC** and **CloudWatch**

## The two-step enablement

Scheduling needs Terraform **and** `config.yaml` to agree, exactly like thread storage:

1. **`deploy/main.tf`** sets the flags, which provision the backends and inject their coordinates:

   ```hcl
   queue_mode                     = true   # mandatory: occurrences arrive on the Input Queue
   enable_scheduling              = true
   create_dynamodb_schedule_table = true
   ```

2. **`config.yaml`** declares *which* backends to use:

   ```yaml
   schedule:
     provider:
       type: eventbridge
     store:
       type: dynamodb
   ```

Terraform injects `AK_SCHEDULE__PROVIDER__EVENTBRIDGE__{GROUP_NAME,ROLE_ARN,QUEUE_ARN}` and
`AK_SCHEDULE__STORE__DYNAMODB__TABLE_NAME`, but never a `type`. Setting the flags **without** the
`config.yaml` block leaves scheduling on the in-process `local` provider and `in_memory` store — the
timers would die with the container while the provisioned group and table sat unused, with no error.
The reverse mistake is safe: declaring the types without the flags fails at startup with an
`AKConfigError` on the missing coordinates.

## Why the input queue changes

`enable_scheduling` flips the **Input Queue** to `content_based_deduplication = true` (an in-place
update; the output queue is untouched). EventBridge Scheduler cannot set a
`MessageDeduplicationId`, so SQS must derive one from the body.

That is safe here because no two occurrences ever produce the same body: the trigger body carries
`request_id` and `scheduled_time` as EventBridge context attributes
(`<aws.scheduler.execution-id>`, `<aws.scheduler.scheduled-time>`) which AWS resolves per firing.
Application senders are unaffected — they always send an explicit `MessageDeduplicationId`, which
takes precedence over content-based dedup.

## Why `app_rest_service.py` is not just `ECSIOHandler.run()`

`ECSIOHandler.run()` builds the FastAPI app from `AWSRestAPI`'s default handlers, which cover chat
only. To serve the management routes this example subclasses `AWSRestAPI` to add
`ScheduleRESTRequestHandler`, then composes the same two peer threads ECSIOHandler runs
(`ThreadRunner` + `ECSOutputConsumer`). All public API, ~30 lines.

The management routes are served **in the REST service**, not through the queues: they read the
shared DynamoDB task store and call Scheduler directly, so a listing or cancellation needs no round
trip.

The routes are **open** in this example. To protect them, pass an `Authoriser`:

```python
class ScheduleAwareRestAPI(AWSRestAPI):
    @classmethod
    def get_default_handlers(cls):
        return AWSRestAPI.get_default_handlers() + [ScheduleRESTRequestHandler(authoriser=MyAuthoriser())]
```

With one configured, listings are forced to the resolved user and touching another user's schedule
is a 403.

## API Gateway routes must be declared

The gateway only proxies paths listed in `gateway_endpoints`. The chat route is added by the module;
the schedule routes are declared in `deploy/main.tf`:

```hcl
gateway_endpoints = [
  {
    path           = "schedules"
    method         = "ANY" # GET (list)
    overwrite_path = "/api/v1/schedules"
  },
  {
    path           = "schedules/{task_id}"
    method         = "ANY" # GET (read), PUT (amend), DELETE (cancel)
    overwrite_path = "/api/v1/schedules/$request.path.task_id"
  },
]
```

`overwrite_path` is the backend path handed to the ALB. It is a **required, non-empty** field on this
module, so each route maps onto *itself* — `ScheduleRESTRequestHandler` declares the real
`/api/v1/schedules...` paths, and FastAPI must see them unchanged.
`$request.path.task_id` is an API Gateway parameter-mapping expression carrying the path parameter
through. Omit these entries and the routes exist inside the container but 404 at the gateway.

## Prerequisites

- An AWS account with permissions for ECS, ECR, SQS, DynamoDB, EventBridge Scheduler, IAM, API
  Gateway and VPC resources
- Terraform >= 1.9.5, Docker, the AWS CLI, and `uv`
- An `OPENAI_API_KEY`
- A VPC and private subnets (or let the module create them by omitting `vpc_id`)

## Deploy

Set the deployment identifiers in `deploy/terraform.tfvars`, then:

```bash
./build.sh                 # or ./build.sh local to build against a local ak-py dist
cd deploy
./deploy.sh                # packages both images, terraform init + apply, waits for ECS stability
```

`deploy.sh` prompts for `openai_api_key`, `vpc_id` and `private_subnet_ids` unless you add them to
`terraform.tfvars` or pass them as `-var` flags.

Take the `agent_invoke_url` output; everything below assumes:

```bash
export AK_TEST_ENDPOINT="$(terraform output -raw agent_invoke_url)"
SCHEDULES="${AK_TEST_ENDPOINT%/chat}/schedules"
```

## Try it

Every scheduling request must carry a `user_id` — it is the owner the task is stored under and the
identity later reads and changes are checked against.

**Defer a chat to a one-time moment.** `at` is a local wall-clock timestamp read in `timezone`, and
must be in the future:

```bash
curl -i -X POST "$AK_TEST_ENDPOINT" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Send me the daily summary", "session_id": "ses-1", "user_id": "alice",
       "schedule": {"at": "2035-01-31T09:00:00", "timezone": "Asia/Colombo"}}'
```

The acknowledgement comes back as **202**, not 200 — the request was accepted, not executed. The
status survives the queue round trip because the agent runner forwards it as a `status_code`
attribute and the output consumer stores it:

```
HTTP/1.1 202 Accepted

{"result":"{\"status\": \"SCHEDULED\", \"scheduled_task_id\": \"74ca19a5-...\", \"session_id\": \"ses-1\"}","session_id":"ses-1"}
```

**Defer a recurring chat.** `cron` is a standard 5-field expression; `session_mode: new` runs each
occurrence in its own fresh session:

```bash
curl -X POST "$AK_TEST_ENDPOINT" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Send the weekly report", "session_id": "ses-2", "user_id": "alice",
       "schedule": {"cron": "0 9 * * 1", "timezone": "Asia/Colombo", "session_mode": "new"}}'
```

**List, read, amend, cancel:**

```bash
curl "$SCHEDULES?user_id=alice"
curl "$SCHEDULES/<task_id>"

# PUT replaces the full amendable state rather than merging — send every value, changed or not.
# `status` is the paused/active switch: a paused schedule keeps its record but stops firing.
curl -X PUT "$SCHEDULES/<task_id>" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Send the weekly report", "cron": "0 8 * * 1", "timezone": "Asia/Colombo",
       "session_mode": "new", "status": "paused"}'

# The record survives as the audit trail, so this returns the task with "status": "cancelled".
curl -X DELETE "$SCHEDULES/<task_id>"
```

**Let the agent schedule the work itself.** This runs now; the agent calls `create_schedule` and
replies with the task id, which then shows up in the listing:

```bash
curl -X POST "$AK_TEST_ENDPOINT" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Every weekday at 8am in Asia/Colombo, remind me to review the overnight alerts.",
       "session_id": "ses-3", "user_id": "alice"}'
```

The five tools (`create_schedule`, `list_schedules`, `get_schedule`, `update_schedule`,
`delete_schedule`) and their guidance are injected into the system prompt automatically — the agent
definition never describes them. Each acts as the **acting user**, so an agent can never reach
another user's schedules.

**Watch an occurrence fire.** Schedule something a couple of minutes out and tail the agent runner:

```bash
aws logs tail "/ecs/<product_alias>-<env_alias>-<module_name>-agent-runner" --follow
```

A fired occurrence arrives as a plain chat request carrying `scheduled_task_id`, `request_id` and
`scheduled_time` **in the body** (EventBridge Scheduler cannot set SQS message attributes, so the
runners fall back to the body), and with **no** `schedule` key — otherwise firing a schedule would
register another one. Afterwards the record shows `trigger_count`, `last_triggered_at` and
`last_request_id`; a fired one-time task reads back as `"status": "completed"`.

## Inspect the AWS side

```bash
GROUP=$(cd deploy && terraform output -raw schedule_group_name)
aws scheduler list-schedules --group-name "$GROUP"
aws scheduler get-schedule --group-name "$GROUP" --name "ak-<task_id>"
```

A one-time schedule carries `ActionAfterCompletion: DELETE`, so AWS retires it after it fires; the
store record remains the audit trail, and cancelling an already-fired task still succeeds.

## Tests

`app_test.py` is an integration suite against the deployed stack. It creates real EventBridge
schedules and cancels them afterwards; it does **not** wait for an occurrence to fire (a schedule
far enough out to be safe is also too far to await), so it covers registration, the 202 contract,
the management surface, validation rejection, and the agent-tool path.

```bash
export AK_TEST_ENDPOINT="$(cd deploy && terraform output -raw agent_invoke_url)"
uv run pytest -s
```

## Tear down

```bash
cd deploy && terraform destroy
```

`terraform destroy` removes the schedule **group**, not the individual schedules the application
registered inside it. Cancel outstanding tasks first (`DELETE /api/v1/schedules/{task_id}`), or
delete the group's schedules directly, otherwise the group deletion fails on a non-empty group:

```bash
aws scheduler list-schedules --group-name "$GROUP" \
  --query 'Schedules[].Name' --output text |
  xargs -n1 -I{} aws scheduler delete-schedule --group-name "$GROUP" --name {}
```

## Related

- Scheduling guide: <https://kernel.yaala.ai/docs/advanced/scheduling>
- Local-only equivalent (no AWS, `local` provider + `in_memory` store):
  `examples/api/schedule-openai`
- Serverless equivalent: `examples/aws-serverless/schedule-openai`
