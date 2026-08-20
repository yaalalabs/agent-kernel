# Release notes draft: #629 scheduling capability

Paste-ready material for the GitHub release that ships #629. The capability lands over six PRs
(`plan.md` phases 1 to 6); this draft accumulates as each phase merges. **Shipped so far: all six
phases** — the shared authorization/pagination refactor, the queue-path groundwork, the scheduling
core, the management API and agent tools, the distributed stores and the EventBridge provider, and
the AWS Terraform support.

## New: scheduled and recurring chats

A chat request can now carry a **`schedule` block** instead of running immediately. Agent Kernel
registers it as a scheduled task and answers **HTTP 202**; when an occurrence is due, the configured
provider delivers the stored prompt into the input queue as a plain chat request and the normal
execution path runs it.

The presence of a `schedule` block in `config.yaml` is the whole switch — no handler to mount, no
code change. Its defaults are what local development needs:

```yaml
schedule:
  provider:
    type: local           # local | eventbridge, or a dotted path to a ScheduleProvider
  store:
    type: in_memory       # in_memory | redis | valkey | dynamodb, or a dotted path to a ScheduleStore
  # agents: [planner]     # agents the schedule tools attach to; omitted = all agents
```

```bash
curl -i -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Send the weekly report", "session_id": "ses-1", "user_id": "alice",
       "schedule": {"cron": "0 9 * * 1", "timezone": "Asia/Colombo", "session_mode": "new"}}'

HTTP/1.1 202 Accepted
{"result":"{\"status\": \"SCHEDULED\", \"scheduled_task_id\": \"74ca19a5-...\", \"session_id\": \"ses-1\"}","session_id":"ses-1"}
```

What ships with it:

- **Two providers.** `local` runs an in-process scheduler thread (development; armed occurrences do
  not survive a restart). `eventbridge` registers one AWS EventBridge Scheduler schedule per task, so
  AWS owns the timers and any process holding the same configuration can amend or cancel them.
- **Four task stores.** `in_memory`, `redis`, `valkey`, and `dynamodb`. Unlike threads, schedule
  records have **no default TTL** — a task that silently expired would stop firing with no audit
  trail.
- **Management routes**, mounted automatically when the block is present: `GET /api/v1/schedules`
  (cursor-paginated), and `GET` / `PUT` / `DELETE /api/v1/schedules/{task_id}` to read, amend and
  cancel. `PUT` is full-replacement. There is deliberately **no POST** — creation is the chat
  block or the agent tool, so callers and agents share one path. Protect them with an `Authoriser`
  (`IOHandler.run(authoriser=...)`); listings are then forced to the resolved user and cross-user
  access is 403.
- **Five agent tools**, injected with their guidance into the system prompt when the block is
  present: `create_schedule`, `list_schedules`, `get_schedule`, `update_schedule`,
  `delete_schedule`. Each acts as the *acting user*, so an agent can never reach another user's
  schedules. Scope them with `schedule.agents`.
- **Startup validation of the topology.** The provider, store and queue transport are checked as a
  set at boot, not at first use: `local` + a broker transport, `local` + a shared store,
  `in_memory` + a broker transport, and `eventbridge` + a non-`sqs` transport each fail fast with
  an `AKConfigError` rather than reporting a successful cancellation whose timer keeps firing.
- **Ownership everywhere.** Every task belongs to a `user_id`; a creation without one is a 400 and
  every later read or change is checked against it.
- **New optional extra**: `pip install "agentkernel[cron]"` (croniter, for cron parsing). The
  EventBridge provider rides the existing `aws` extra.

Docs: [Scheduled Tasks](https://kernel.yaala.ai/docs/advanced/scheduling). Runnable example:
`examples/api/schedule-openai`.

### Deploying it on AWS

Both AWS Terraform stacks (serverless and containerized) gained two flags, off by default:

| Flag | Provisions | Injects |
|---|---|---|
| `enable_scheduling` | An EventBridge Scheduler schedule group, the execution role Scheduler assumes to deliver triggers to the input queue, and `scheduler:*Schedule` + `iam:PassRole` on both the request/REST and agent-runner roles. Requires `queue_mode = true`. | `AK_SCHEDULE__PROVIDER__EVENTBRIDGE__GROUP_NAME`, `__ROLE_ARN`, `__QUEUE_ARN` |
| `create_dynamodb_schedule_table` | A DynamoDB table (partition `task_id`, no sort key, no GSI, TTL on `expiry_time`) | `AK_SCHEDULE__STORE__DYNAMODB__TABLE_NAME` |

As with `thread.type`, Terraform never injects `schedule.provider.type` or `schedule.store.type` —
declare those in the application's committed `config.yaml`, or the injected coordinates alone leave
scheduling on the `local`/`in_memory` defaults while the provisioned group and table sit unused.

Five new outputs on each stack (`schedule_group_name`, `schedule_group_arn`,
`scheduler_execution_role_arn`, `schedule_table_name`, `schedule_table_arn`), all null unless the
matching flag is set.

## Breaking changes

**`execution.queues.type` is now mandatory inside a declared `queues` block.**
The transport used to be inferred when `type` was absent: a configured `input.url` implied `sqs`,
anything else `in_memory`. Queue coordinates are injected per component by a deployment, though — a
Lambda that consumes its input queue through an event source mapping is never given the input URL —
so the inference made one process resolve `sqs` while its sibling resolved `in_memory`. The
transport decides the deployment topology, so the application now declares it.

Any existing `config.yaml` that declares an `execution.queues` block without `type` fails to load:

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for AKConfig
execution.queues.type
  Field required [type=missing, input_value={'input': {'url': 'https:...'}}, input_type=dict]
```

Before:

```yaml
execution:
  mode: rest_sync
  queues:
    input:
      url: https://sqs.us-east-1.amazonaws.com/123456789012/ak-input.fifo
```

After:

```yaml
execution:
  mode: rest_sync
  queues:
    type: sqs          # in_memory | sqs | kafka | nats, or a dotted path to a QueueTransport
    input:
      url: https://sqs.us-east-1.amazonaws.com/123456789012/ak-input.fifo
```

Omitting the `queues` block entirely is unaffected and still runs the single-process `in_memory`
transport, so an application that never declared one needs no change. See the
[Queue Mode Guide](https://kernel.yaala.ai/docs/advanced/queue-mode-guide) for the per-transport values.

**`Authoriser` now lives in `agentkernel.auth`.**
`Authoriser` was defined inside the thread integration, which made it look thread-specific. It is
the generic authorization hook for *any* resource-management route (threads today, scheduled tasks
next), so it moved next to `AuthValidator` in `agentkernel.auth` — one import path, matching how
`AuthValidator` is already imported.

Before:

```python
from agentkernel.thread import Authoriser              # or agentkernel.integration.thread
```

After:

```python
from agentkernel.auth import Authoriser
```

The class itself is unchanged: same `authorise(token) -> Optional[str]` contract, same runtime
behavior, same 401 detail strings on the routes that use it. Apps that subclass it update one import
line and nothing else. `agentkernel.thread` and `agentkernel.integration.thread` no longer expose an
`Authoriser` attribute, so a stale import fails loudly at import time rather than silently.

**`schedule`, `scheduled_task_id` and `scheduled_time` are now reserved chat-request keys.**
They used to fall through to the agent as unknown `AgentRequestAny` context; they are now typed
fields with meaning. A JSON chat request carrying a `schedule` key defers the execution when the
capability is configured, and is rejected with 400 `"Scheduling is not configured. Add a 'schedule'
block to config.yaml"` when it is not. If your application sent any of these three names as
free-form context, rename them.

**ECS REST_SYNC/REST_ASYNC error replies now surface as HTTP 4xx/5xx.**
An ECS-mode reply whose stored status is >= 400 previously came back as HTTP 200 with an error body.
It now raises the same `HTTPException` the direct and pipeline modes already raised. Clients that
keyed off the 200 status and parsed the body for errors will start seeing real error codes; this is
parity with every other deployment mode. Non-error responses are byte-identical.

## Improvements

- **New `AuthValidatorAuthoriser` adapter.** One user-supplied `AuthValidator` can now protect the
  global REST routes, WebSocket `$connect`, *and* the resource-management routes — wrap it rather
  than writing a second implementation:

  ```python
  from agentkernel.auth import AuthValidatorAuthoriser
  from agentkernel.thread import AgentThreadRequestHandler

  RESTAPI.run(handlers=[AgentThreadRequestHandler(authoriser=AuthValidatorAuthoriser(MyValidator()))])
  ```

- **Shared `AuthorisedRESTRequestHandler` base** (`agentkernel.api.handler`). Bearer parsing and 401 mapping
  live in one place; `ThreadRESTRequestHandler` now inherits `_resolve_user` from it instead of
  carrying its own copy. Behavior and error strings are identical. Custom management handlers can
  subclass it to get token handling for free.
- **Shared cursor-pagination helpers** (`agentkernel.core.util.pagination`): `encode_cursor`,
  `decode_cursor`, `clamp_limit`, and `MAX_PAGE_SIZE`. Extracted verbatim from the thread manager,
  which now delegates to them. Stores stay in plain `(limit, offset)` terms; the service layer owns
  the opaque cursor. Existing thread cursors are unchanged and remain valid.
- **Queue runners accept request metadata from the message body.** `request_id` and `user_id` are
  resolved from message attributes first, falling back to the body when an attribute is absent
  (pipeline, ECS, and serverless runners alike). A message carrying `request_id` in its body no
  longer permanently fails; messages missing the key in *both* places keep today's error path. This
  is the contract scheduler-emitted trigger messages use.
- **Queue paths preserve non-200 success statuses.** `ECSAgentRunner` forwards `ChatService`'s
  status code instead of discarding it, `ECSOutputConsumer` persists it (records gain an additive
  `status_code` key, defaulting to 200 and 500 on permanent failure), and sync/poll responses honor
  the stored status. A future 202 acknowledgement survives the round trip end to end.
- **A deferred chat returns HTTP 202 on every surface**: direct REST (via a `JSONResponse`), through
  the pipeline waiter/poller, and on ECS, where the queue runners forward it as a `status_code`
  attribute. Streaming surfaces yield the acknowledgement as a single terminal chunk — deliberately
  not an error chunk, since deferring was the requested outcome.
- **`IOHandler` mounts the schedule management routes automatically** whenever a `schedule` block is
  present, and calls `ScheduleManager.get()` eagerly at startup, so an unusable provider/transport
  pairing or an incomplete provider config fails the boot rather than the first request.
  `RESTAPI.run()`'s delegation rule is untouched; an app needing an `Authoriser` in this topology
  calls `IOHandler.run(authoriser=...)` directly.
- **Deferred requests create no thread.** `AgentThreadRequestHandler` checks for the `schedule` block
  before `ThreadRecorder.pre_run`, so a deferral neither creates a thread nor records messages. The
  occurrences that later fire do.
- **The AWS input queue flips to content-based deduplication under `enable_scheduling`** (an
  in-place update). EventBridge Scheduler cannot set a `MessageDeduplicationId`, so without it two
  occurrences carrying an otherwise identical trigger body would collapse into one inside the
  5-minute window. Application senders are unaffected — they always send an explicit
  `MessageDeduplicationId`, which takes precedence. The output queue is untouched.
- **Acting user is visible to hooks and tools.** A run whose request carries `user_id` exposes it in
  the session's volatile cache under `ak.acting_user_id` for the duration of that run:

  ```python
  from agentkernel.core import ACTING_USER_CACHE_KEY

  user_id = Session.current().get_volatile_cache().get(ACTING_USER_CACHE_KEY)
  ```

  `Runtime` both sets and clears the key inside the per-session lock, so it never leaks into another
  run and concurrent runs on one session cannot clobber each other. `AgentHandler.run_*`,
  `AgentService.run_multi`/`stream_multi`, and `Runtime.run`/`stream` each gain a backward-compatible
  optional `acting_user_id` parameter; existing callers are unaffected.

## Notes for maintainers

- Behavioral details and the full change inventory: `docs/specs/629-scheduled-tasks/spec.md`
  (Behavioural changes, all 11 items).
- Phased breakdown and per-phase sync steps: `docs/specs/629-scheduled-tasks/plan.md`.
- `docs/versioned_docs/` is a frozen release snapshot and intentionally still shows the old
  `Authoriser` import path.
