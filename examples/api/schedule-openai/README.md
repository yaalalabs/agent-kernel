# Agent Kernel Scheduled Chats with OpenAI Agent SDK Agents on a REST API

This package contains a demo of the Agent Kernel scheduling capability with an agent built using the
OpenAI Agents SDK. A chat request that carries a `schedule` block is not run — it is registered as a
scheduled task and acknowledged with HTTP 202. When an occurrence is due, the provider delivers the
stored prompt into the input queue as a plain chat request, and the normal execution path runs it.

The `schedule` block in `config.yaml` is what enables the capability. It selects two backends: the
**provider** that owns the timers and the **store** that persists the task records. This example
uses the defaults — the `local` provider (an in-process scheduler thread) and the `in_memory` store
— which need nothing but the process itself. Neither survives a restart; this demo currently
supports only the `local` provider and `in_memory` store.
That pairing is also a hard requirement rather than a default: the `local` provider's timers and the
`in_memory` store's records are reachable only from the process that owns them, so `ScheduleManager`
refuses at startup if either is combined with a broker transport (`sqs`/`kafka`/`nats`) or a shared store.
A broker transport puts the management routes in a different process from the scheduler thread, where a
cancellation would report success while the timer kept firing.

The management routes (`GET`/`PUT`/`DELETE /api/v1/schedules`) are mounted by the app, exactly like
a Slack handler: `app.py` passes `ScheduleRESTRequestHandler()` to `IOHandler.run()`. Deferring a
chat and the agent's own scheduling tools need no handler at all; only the management routes do.

Who is calling comes from the `identity` block in `config.yaml`, which names the provider that turns
the bearer token into the request's principal. A task belongs to the principal whose request created
it, so the management routes serve authenticated callers only (401 without a token), listings are
always the caller's own, and reading or changing another user's schedule is a 403. Here the `static`
provider maps one credential to the principal `alice`; the credential's value is not in the file but
resolved from the environment (`ALICE_TOKEN`) when the app starts. To validate real tokens, swap the
provider for `oidc` (Auth0, Keycloak, Okta or any other OIDC issuer), `cognito`, `entra` or
`firebase`; [`examples/aws-serverless/openai-auth`](../../aws-serverless/openai-auth/README.md) shows
an Auth0 block.

The same capability is available to the agent itself: Agent Kernel injects the scheduling tools
(`create_schedule`, `list_schedules`, `get_schedule`, `update_schedule`, `delete_schedule`) and
their guidance into every agent's system prompt, so the assistant can defer work when a user asks
it to — the agent authors never describe these tools in their own instructions.

Every scheduling request must carry a bearer token: the principal it authenticates is the owner the
task is stored under and the identity later reads and changes are checked against. A request nothing
authenticated cannot schedule (403), and a `user_id` in the body is a 400: the acting user comes from
the credential, never from the client.

`OPENAI_API_KEY` and `ALICE_TOKEN` must be set in the environment:

    export OPENAI_API_KEY=sk-...
    export ALICE_TOKEN=alice-token

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Run this demo using the following.

Run REST API:

    python app.py

Defer a chat to a one-time moment — `at` is a local wall-clock timestamp read in `timezone`, and
must be in the future:

    curl -i -X POST http://localhost:8000/api/v1/chat \
      -H "Authorization: Bearer alice-token" \
      -H "Content-Type: application/json" \
      -d '{"prompt": "Send me the daily summary", "session_id": "ses-1",
           "schedule": {"at": "2030-01-31T09:00:00", "timezone": "Asia/Colombo"}}'

The acknowledgement carries the task id and comes back as 202, not 200 — the request was accepted,
not executed:

    HTTP/1.1 202 Accepted
    content-type: application/json

    {"result":"{\"status\": \"SCHEDULED\", \"scheduled_task_id\": \"74ca19a5-e610-4e39-8264-541ec6ab5352\", \"session_id\": \"ses-1\"}","session_id":"ses-1"}

Defer a recurring chat — `cron` is a standard 5-field expression, and `session_mode: new` runs each
occurrence in its own fresh session instead of continuing `ses-2`:

    curl -i -X POST http://localhost:8000/api/v1/chat \
      -H "Authorization: Bearer alice-token" \
      -H "Content-Type: application/json" \
      -d '{"prompt": "Send the weekly report", "session_id": "ses-2",
           "schedule": {"cron": "0 9 * * 1", "timezone": "Asia/Colombo", "session_mode": "new"}}'

An unusable schedule is rejected at creation rather than at fire time:

    curl -i -X POST http://localhost:8000/api/v1/chat \
      -H "Authorization: Bearer alice-token" \
      -H "Content-Type: application/json" \
      -d '{"prompt": "Send me the daily summary", "session_id": "ses-1",
           "schedule": {"at": "2020-01-01T09:00:00"}}'

    HTTP/1.1 400 Bad Request

    {"detail":{"error":"schedule 'at' must be in the future: '2020-01-01T09:00:00' has already passed in UTC","session_id":"ses-1"}}

List the caller's schedules (most recently updated first; the listing is always the caller's own):

    curl http://localhost:8000/api/v1/schedules -H "Authorization: Bearer alice-token"

    {
      "schedules": [
        {
          "task_id": "ae9a043b-27f7-480f-8655-5903fbfd200a",
          "user_id": "alice",
          "prompt": "Send the weekly report",
          "agent": null,
          "session_id": "ses-2",
          "spec": {"at": null, "cron": "0 9 * * 1", "timezone": "Asia/Colombo", "session_mode": "new"},
          "status": "active",
          "provider_ref": "ae9a043b-27f7-480f-8655-5903fbfd200a",
          "created_at": "2026-08-18T07:04:04.177184+00:00",
          "updated_at": "2026-08-18T07:04:04.178100+00:00",
          "last_triggered_at": null,
          "trigger_count": 0,
          "last_request_id": null
        }
      ],
      "next_cursor": null
    }

Read one schedule (`trigger_count`, `last_triggered_at` and `last_request_id` track its
occurrences, so a fired one-time task reads back as `"status": "completed"` with
`"trigger_count": 1`):

    curl http://localhost:8000/api/v1/schedules/ae9a043b-27f7-480f-8655-5903fbfd200a \
      -H "Authorization: Bearer alice-token"

Amend a schedule. `PUT` replaces the full amendable state rather than merging, so send every value,
including the ones that are not changing. `status` covers the paused/active switch — a paused
schedule keeps its record but stops firing:

    curl -X PUT http://localhost:8000/api/v1/schedules/ae9a043b-27f7-480f-8655-5903fbfd200a \
      -H "Authorization: Bearer alice-token" \
      -H "Content-Type: application/json" \
      -d '{"prompt": "Send the weekly report", "cron": "0 8 * * 1", "timezone": "Asia/Colombo",
           "session_mode": "new", "status": "paused"}'

Cancel a schedule. The record survives as the audit trail, so the response is the task with
`"status": "cancelled"`:

    curl -X DELETE http://localhost:8000/api/v1/schedules/ae9a043b-27f7-480f-8655-5903fbfd200a \
      -H "Authorization: Bearer alice-token"

Let the agent schedule the work itself — this runs now, and the assistant calls `create_schedule`
and replies with the task id it registered, which then shows up in `GET /api/v1/schedules`:

    curl -X POST http://localhost:8000/api/v1/chat \
      -H "Authorization: Bearer alice-token" \
      -H "Content-Type: application/json" \
      -d '{"prompt": "Every weekday at 8am in Asia/Colombo, remind me to review the overnight alerts.",
           "session_id": "ses-3"}'

To run tests (the suite starts `app.py` with the token above):

    uv run pytest -s
