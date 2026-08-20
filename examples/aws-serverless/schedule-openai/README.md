# Agent Kernel Scheduled & Recurring Chats on AWS Lambda

This package demonstrates the Agent Kernel **scheduling capability** deployed on AWS Lambda: a chat
request carrying a `schedule` block is not run — it is registered as a scheduled task and
acknowledged with **HTTP 202**. When an occurrence is due, AWS EventBridge Scheduler delivers the
stored prompt into the Input Queue as a plain chat request, and the agent-runner Lambda executes it
through the normal path.

Nothing in `lambda_agent_runner.py` mentions scheduling. The `schedule` block in `config.yaml` is
the whole switch.

## Architecture Overview

- **Request-handler Lambda** — chat ingress (enqueue + poll the response store) plus the custom
  scheduled-task management routes (see [Management routes are custom
  here](#management-routes-are-custom-here)).
- **Agent-runner Lambda** — triggered by the Input Queue event source mapping. It runs fired
  occurrences *and* registers new tasks, whether the request carried a `schedule` block or the agent
  called `create_schedule` itself.
- **Response-handler Lambda** — triggered by the Output Queue, writes replies to the response store.
- **EventBridge Scheduler** — owns the timers. One schedule per task, named `ak-<task_id>`, inside a
  schedule group Terraform provisions, targeting the Input Queue.
- **DynamoDB** — session store, response store, and the **schedule store** holding task records.

```
POST /api/v1/chat  {"schedule": {...}}       POST /api/v1/chat  (no schedule)
        |                                            |
  Request Handler --> Input Queue --> Agent Runner --> Output Queue --> Response Handler
        |                   ^              |                                  |
        |                   |              +--> registers ak-<task_id> in the  |
        |                   |                   group, writes the record       |
        |             EventBridge Scheduler                                    v
        |             (fires each occurrence)                          Response Store
        |                                                                     |
        +-- polls the response store for the reply (rest_sync) ---------------+
        |
  GET /schedules, /schedules/get, POST /schedules/amend, /schedules/cancel
        (custom Lambda.register routes -> ScheduleManager, direct, no queue round trip)
```

## Deployed Resources

- **Lambda functions**: request handler and response handler in **zip mode** (`LocalZip`), agent
  runner in **image mode** (`Image`) with an ECR repository Terraform creates and pushes to
- **SQS**: FIFO input and output queues. The input queue runs with **content-based deduplication** —
  see [Why the input queue changes](#why-the-input-queue-changes)
- **EventBridge Scheduler**: a schedule group plus the execution role Scheduler assumes to send to
  the input queue
- **DynamoDB**: session store, response store, schedule store (partition `task_id`, no sort key)
- **IAM**: `scheduler:{Create,Update,Delete,Get}Schedule` + `iam:PassRole` on both the
  request-handler and agent-runner roles
- **API Gateway**: REST API with the chat route and the four management routes

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
`config.yaml` block leaves scheduling on the in-process `local` provider and `in_memory` store —
neither of which survives a Lambda invocation — while the provisioned group and table sit unused,
with no error. The reverse mistake is safe: declaring the types without the flags fails at startup
with an `AKConfigError` on the missing coordinates.

## Management routes are custom here

This is the one real difference from the containerized target. `ScheduleRESTRequestHandler` is a
FastAPI `APIRouter`, and the serverless target's router is **not** FastAPI — it is a hand-rolled
path/method table — so it cannot be mounted. `lambda_request_handler.py` exposes management through
`Lambda.register` routes that call `ScheduleManager` directly, which is the same object the REST
handler wraps.

Two consequences of the router matching paths exactly:

- **No `{task_id}` path parameters.** The task id travels as a query parameter or in the body.
- **Every path must also be declared in `gateway_endpoints`** in `deploy/main.tf`, or it 404s at the
  gateway.

| This example | Containerized / self-hosted equivalent |
|---|---|
| `GET /api/v1/schedules?user_id=` | `GET /api/v1/schedules` |
| `GET /api/v1/schedules/get?user_id=&task_id=` | `GET /api/v1/schedules/{task_id}` |
| `POST /api/v1/schedules/amend` (task_id in body) | `PUT /api/v1/schedules/{task_id}` |
| `POST /api/v1/schedules/cancel` (task_id in body) | `DELETE /api/v1/schedules/{task_id}` |

Creation is deliberately absent from both, identically: a task is created by the `schedule` block on
a chat request or by the agent's own `create_schedule` tool, so callers and agents share one path.

**Ownership in this example is taken from the request**, not from a token — `user_id` is a query
parameter or body field. That is fine for a demo and wrong for production: resolve the caller from
an API Gateway authorizer (see `examples/aws-serverless/openai-auth`) and ignore any client-supplied
`user_id`. On the containerized target this is what an `Authoriser` on
`ScheduleRESTRequestHandler` does for you.

## Why the input queue changes

`enable_scheduling` flips the **Input Queue** to `content_based_deduplication = true` (an in-place
update; the output queue is untouched). EventBridge Scheduler cannot set a
`MessageDeduplicationId`, so SQS must derive one from the body.

That is safe because no two occurrences ever produce the same body: the trigger body carries
`request_id` and `scheduled_time` as EventBridge context attributes
(`<aws.scheduler.execution-id>`, `<aws.scheduler.scheduled-time>`) which AWS resolves per firing.
Application senders are unaffected — they always send an explicit `MessageDeduplicationId`, which
takes precedence.

## Prerequisites

- An AWS account with permissions for Lambda, ECR, SQS, DynamoDB, EventBridge Scheduler, IAM, API
  Gateway and VPC resources
- Terraform >= 1.9.5, the AWS CLI, `uv`, `zip`, and a running Docker daemon (the agent runner image
  is built and pushed during `terraform apply`)
- An `OPENAI_API_KEY`
- A VPC and private subnets

## Deploy

Set the deployment identifiers in `deploy/terraform.tfvars`, then:

```bash
./build.sh                 # or ./build.sh local to build against a local ak-py dist
cd deploy
./deploy.sh                # packages all three functions, terraform init + apply
```

`deploy.sh` zips the request and response handlers into `dist_request_handler.zip` /
`dist_response_handler.zip`, and stages the agent runner into `dist_agent_runner/` (dependencies
and entrypoint under `data/`, plus the `Dockerfile.agent_runner` it copies in as `Dockerfile`) for
Terraform to build. Pass `local` (`./deploy.sh local`) to install `agentkernel` from
`../../../ak-py/dist` instead of PyPI.

### Why the agent runner is an image

Lambda caps a zip-deployed function at **250 MB unzipped**. The agent runner carries
`agentkernel[aws,openai,cron]` including the OpenAI Agents SDK, which does not fit — hence
`package_type = "Image"` for that one function. The request and response handlers stay small by
design: their `pyproject.toml` extras omit the OpenAI SDK entirely, since they only enqueue and
dequeue work, so they stay on zip mode. `deploy.sh` prints their zipped and unzipped sizes and
warns if either one starts to approach the limit.

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

The acknowledgement comes back as **202**, not 200 — accepted, not executed. The status survives the
queue round trip because the agent runner forwards it and the response store keeps it:

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
curl "$SCHEDULES/get?user_id=alice&task_id=<task_id>"

# Full replacement rather than a merge — send every value, changed or not. `status` is the
# paused/active switch: a paused schedule keeps its record but stops firing.
curl -X POST "$SCHEDULES/amend" \
  -H "Content-Type: application/json" \
  -d '{"task_id": "<task_id>", "user_id": "alice", "prompt": "Send the weekly report",
       "cron": "0 8 * * 1", "timezone": "Asia/Colombo", "session_mode": "new", "status": "paused"}'

# The record survives as the audit trail, so this returns the task with "status": "cancelled".
curl -X POST "$SCHEDULES/cancel" \
  -H "Content-Type: application/json" \
  -d '{"task_id": "<task_id>", "user_id": "alice"}'
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

**Watch an occurrence fire.** Schedule something a couple of minutes out and tail the runner:

```bash
aws logs tail "/aws/lambda/<product_alias>-<env_alias>-agent-runner-ar-func" --follow
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

`lambda_test.py` is an integration suite against the deployed stack. It creates real EventBridge
schedules and cancels them afterwards; it does **not** wait for an occurrence to fire (a schedule
far enough out to be safe is also too far to await), so it covers registration, the 202 contract,
the management surface, validation rejection, and the agent-tool path. Cold starts are retried.

```bash
export AK_TEST_ENDPOINT="$(cd deploy && terraform output -raw agent_invoke_url)"
uv run pytest -s
```

## Tear down

```bash
cd deploy && terraform destroy
```

`terraform destroy` removes the schedule **group**, not the individual schedules the application
registered inside it. Cancel outstanding tasks first, or delete the group's schedules directly,
otherwise the group deletion fails on a non-empty group:

```bash
aws scheduler list-schedules --group-name "$GROUP" \
  --query 'Schedules[].Name' --output text |
  xargs -n1 -I{} aws scheduler delete-schedule --group-name "$GROUP" --name {}
```

## Related

- Scheduling guide: <https://kernel.yaala.ai/docs/advanced/scheduling>
- Local-only equivalent (no AWS, `local` provider + `in_memory` store):
  `examples/api/schedule-openai`
- Containerized equivalent, with the real `ScheduleRESTRequestHandler` routes:
  `examples/aws-containerized/openai-schedule`
