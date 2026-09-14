---
slug: /scheduled-tasks
title: "Scheduled Tasks in Agent Kernel: Work That Runs Without Anyone Asking"
authors: [induwara]
tags: [agent-kernel, scheduling, cron, eventbridge, automation, queue-mode, enterprise-ai]
image: /img/card.png
description: Your agent can now work on a clock. Tell it "every weekday at 8am" and Agent Kernel remembers, wakes up on time, and runs the request exactly as if you had just typed it.
---

# Scheduled Tasks in Agent Kernel: Work That Runs Without Anyone Asking

**Imagine hiring a brilliant assistant who never speaks unless spoken to.**

Ask them anything and you get a thoughtful answer in seconds. But say *"remind me about this on Monday"* and they just stare back. They have no calendar, no alarm clock, no way to act on their own. Every single thing they do, you have to be present to ask for.

That is every AI agent today. Agents are excellent at answering. The other half of real work is the part nobody is around to ask for: the 8am summary, the Monday report, the follow-up three days from now.

Most teams bolt that on from the outside — a cron container, a Lambda, a separate service that pokes the agent API on a timer. Now you're running two systems instead of one, deploying twice, and the agent still can't put anything in its own calendar.

**Agent Kernel puts the clock inside the kernel.** Any request to your agent can carry a `schedule` block, and that block means exactly one thing: *not now*.

<!-- truncate -->

## What This Changes, Before Any Code

If you never read a line of the code below, this is what's different:

- **Your agent can work while nobody is watching.** The overnight alert digest, the Monday morning report, the "check back on this in three days" — these now happen on their own.
- **Users can schedule things in plain English.** "Every weekday at 8am, remind me to review the overnight alerts" is a sentence, not a ticket for an engineer. The agent understands it and books it itself.
- **There is no second system to build, deploy, or pay for.** No cron server, no scheduling microservice. It's a setting, not a project.
- **A scheduled run behaves like a live one.** Every safety check, log, memory and tool that applies when a person is typing applies identically at 3am when nobody is. Nothing gets a special, less-supervised path.
- **Nothing happens in the dark.** Every scheduled task is owned by a specific user, and every run it produces is traceable back to it. Cancelling something keeps the record, so the history of what was scheduled — and by whom — survives.

That's the product. Here's the engineering.

## One Idea: A Schedule Block Means "Not Now"

Here is the whole feature in a single request:

```bash
curl -i -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Send me the daily summary",
       "session_id": "ses-1", "user_id": "alice",
       "schedule": {"at": "2030-01-31T09:00:00", "timezone": "Asia/Colombo"}}'
```

It's an ordinary chat request with one extra key. And you don't get an agent reply back — you get a receipt:

```http
HTTP/1.1 202 Accepted

{"result":"{\"status\": \"SCHEDULED\", \"scheduled_task_id\": \"74ca19a5-...\", \"session_id\": \"ses-1\"}","session_id":"ses-1"}
```

**202, not 200.** That status code is the whole story in two digits: *accepted, not executed*. Hold on to the `scheduled_task_id` — that's your handle for checking, changing or cancelling it later.

Swap `at` for a `cron` expression and it repeats forever instead of firing once:

```json
{"schedule": {"cron": "0 9 * * 1", "timezone": "Asia/Colombo", "session_mode": "new"}}
```

That's `0 9 * * 1` — nine in the morning, every Monday. Four fields is the entire contract:

| Field | What it does |
| --- | --- |
| `at` | Run once, at this wall-clock time. Must be in the future. |
| `cron` | Run repeatedly, on this standard 5-field cron rhythm. |
| `timezone` | The timezone those times mean. Defaults to UTC — set it, or "9am" won't be the 9am your users live in. |
| `session_mode` | `reuse` continues the original conversation; `new` gives each run a clean slate. |

Every chat surface behaves identically, because the check for that block runs at the top of all four `ChatService` entry points — before validation, before agent selection. There is no surface where scheduling works slightly differently.

## How It Fits Together

![Agent Kernel scheduling architecture: chat requests, agent tools and management routes all reach one ScheduleManager, which persists a record to a ScheduleStore and registers a timer with a ScheduleProvider; the provider fires each occurrence into the input queue, where the ordinary agent runner executes it](/img/blog/scheduling-architecture.svg)

Four beats, left to right:

1. **Three doors, one room.** A `schedule` block on a chat request, the `create_schedule` agent tool, or the management routes — all three land on the same object, so they cannot drift apart in behaviour. (There is deliberately no `POST /api/v1/schedules`: creating a schedule *is* sending a chat request you want run later.)
2. **`ScheduleManager` owns the lifecycle.** It validates the timing rule up front — a malformed cron fails now, at creation, not silently at 3am six weeks from now. It enforces that every task belongs to a `user_id`. It writes the record *before* arming the timer, rolling the record back if arming fails, so you never end up with a timer nobody has a record of. And it freezes the exact request body each run will deliver.
3. **Two pluggable backends.** A **store** remembers *what* was scheduled; a **provider** owns the alarm clock that decides *when*. Neither knows the other exists, which is what lets you swap either one for your environment.
4. **The run rejoins the normal path.** When a task comes due, the provider drops a message into the ordinary input queue and the ordinary agent runner picks it up. Nothing about execution is special-cased for schedules.

## Every Scheduled Run Is Just a Normal Request

This is the design decision everything else hangs off, and it's worth stating plainly: **the agent never finds out it was scheduled.**

What the provider fires isn't some internal event type with its own code path. It's a plain chat request, indistinguishable from one a person just typed:

```json
{"prompt": "Send the weekly report", "agent": null, "user_id": "alice",
 "session_id": "ses-2",
 "scheduled_task_id": "<task_id>",
 "request_id": "<per-occurrence id>",
 "scheduled_time": "<occurrence time>"}
```

Note what's **missing**: there is no `schedule` key. A run executes — it does not register another schedule. (A trigger that re-registered itself is the kind of bug that quietly multiplies.) And `scheduled_task_id` / `scheduled_time` are bookkeeping, stripped before the prompt is assembled, so they never leak into the agent's context as stray noise.

The payoff is that hooks, guardrails, tracing, memory, threads and tools all behave on a scheduled run exactly as they do on a live one — because to the runtime, it *is* a live one. **Your agent code needs no scheduling branch, because it has no way to detect one.**

The one thing you do choose is memory. With `session_mode: reuse`, the run continues the original conversation — right for a follow-up that needs the earlier context. With `session_mode: new`, each run starts fresh — right for a recurring report that shouldn't drag last week's thread along behind it.

## Agents Can Schedule Their Own Work

Turn scheduling on and every agent quietly gains five tools, with usage guidance injected into its system prompt. You write no tool descriptions and no glue:

`create_schedule` · `list_schedules` · `get_schedule` · `update_schedule` · `delete_schedule`

Which means this — an ordinary sentence, no `schedule` block at all — just works:

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Every weekday at 8am in Asia/Colombo, remind me to review the overnight alerts.",
       "session_id": "ses-3", "user_id": "alice"}'
```

The agent reads the intent, picks the cron rhythm, and books it. Users get a calendar without learning a syntax.

The obvious worry with a self-scheduling agent is blast radius, so the boundary is structural rather than advisory: every tool acts strictly as the **acting user** — the `user_id` of the run that invoked it. An agent physically cannot see or touch another user's schedules, and a run carrying no user identity gets an error rather than an anonymous create. If you'd rather only some agents have a calendar at all, scope it with `schedule.agents: [planner]`.

## Pick Backends for Where You Run

Remember the two jobs: the **store** remembers what was scheduled, the **provider** owns the alarm clock. On a laptop, both live inside your process:

```yaml title="config.yaml"
schedule:
  provider:
    type: local           # one daemon thread over a heap of armed occurrences
  store:
    type: in_memory

execution:
  mode: rest_sync
  queues:
    type: in_memory
```

In production on AWS, AWS owns the timers and DynamoDB owns the records — so nothing is forgotten when a container restarts:

```yaml title="config.yaml"
schedule:
  provider:
    type: eventbridge     # one EventBridge Scheduler schedule per task
  store:
    type: dynamodb

execution:
  queues:
    type: sqs
```

**The application code is byte-for-byte identical between those two.** Only the config moved. Terraform provisions the schedule group, the execution role and the table, then injects their coordinates — you never type those names yourself. (If you're not on DynamoDB, `redis` and `valkey` stores work too.)

Because runs are delivered *into the input queue*, scheduling needs the queue execution pipeline. On a laptop the `in_memory` transport satisfies that inside a single process, so there's nothing to stand up; on AWS it means `queue_mode = true`.

**Mismatched pairings fail when the scheduling manager is initialized, not necessarily at process startup.** A `local` provider behind an SQS transport would put the management routes in one process and the live timers in another — so a cancellation would report cheerful success while the timer kept right on firing. That's the class of bug you find out about from a customer. Agent Kernel rejects that pairing once the scheduling manager is built.

## Managing What You Scheduled

Mount one handler and you get the management surface:

```python title="app.py"
from agentkernel.pipeline import IOHandler
from agentkernel.schedule import ScheduleRESTRequestHandler

if __name__ == "__main__":
    IOHandler.run(handlers=[ScheduleRESTRequestHandler()])
```

```bash
curl "http://localhost:8000/api/v1/schedules?user_id=alice&limit=20"   # list
curl -X DELETE http://localhost:8000/api/v1/schedules/{task_id}         # cancel
```

Two behaviours worth knowing before you build a UI on top of these:

- **`PUT` replaces the full amendable state — it does not merge.** Send every value, including the ones that aren't changing, or you'll clear them. Read the task with `GET` first if you don't already hold it.
- **Nothing is ever really deleted.** Pausing keeps the record and stops the firing. Cancelling is a status transition, not a delete — the record survives as the audit trail, alongside `trigger_count`, `last_triggered_at`, and the `last_request_id` that ties a task to the exact run it produced.

One caution worth repeating loudly: these routes are **open until you configure an `Authoriser`**. Without one, any caller can list and change anyone's schedules just by passing a `user_id`. Supply one that resolves the caller's identity from a Bearer token and listings are forced to that user, while reaching for someone else's schedule returns 403. Do that before these routes face the internet.

## The Bottom Line

Scheduling is the difference between an agent that **responds** and an agent that **operates**.

Agent Kernel makes it a property of the request rather than a service you bolt on beside it: add a `schedule` block and the request is registered instead of run, then fires later down the exact same path a live request takes — same guardrails, same tracing, same code.

Your assistant finally has a calendar.

Agent Kernel is open source under Apache 2.0.

- Scheduling documentation: https://kernel.yaala.ai/docs/advanced/scheduling
- Runnable example: [`examples/api/schedule-openai`](https://github.com/yaalalabs/agent-kernel/tree/main/examples/api/schedule-openai)
- On AWS: [`examples/aws-containerized/openai-schedule`](https://github.com/yaalalabs/agent-kernel/tree/main/examples/aws-containerized/openai-schedule) · [`examples/aws-serverless/schedule-openai`](https://github.com/yaalalabs/agent-kernel/tree/main/examples/aws-serverless/schedule-openai)
- GitHub: https://github.com/yaalalabs/agent-kernel

`pip install "agentkernel[cron]"` and give your agents a clock.
