# Blockers: removing direct (non-queue) mode

Things that only work in direct mode today. Each one must be fixed, or explicitly accepted, before direct mode can be deleted.

_Line refs are at `develop` @ `29dd1701`. Status checked 2026-10-30._

| # | Blocker | Evidence | Fix | Tracking | Status |
| --- | --- | --- | --- | --- | --- |
| B1 | A2A and MCP run the agent inline in the web server | `api/a2a/a2a.py:60-63`, `api/mcp/akmcp.py:62` | Enqueue and wait on the response store; keep the `ToolResult`/`media_type` mapping | #780, PR #829 (+ PR #842 builds on it) | **In review.** #829 removes the direct path, so B1 is closed once it merges. A2A/MCP on the split ECS setup still wait for B2. |
| B2 | ECS can't mount the handlers that only run on the shared queue code (threads, queue-based AG-UI, webhooks; A2A/MCP once #829 lands). ECS also never delivers messaging replies. | `ecs_io_handler.py:64-72` → `api/http.py:117-131` | Rebuild ECS on the shared queue classes: `AgentRunner`, `ResponseHandler`, `IOHandler` (`docs/specs/495-onprem-kubernetes/plan.md:318`) | new issue, or #798 | **No issue yet.** Biggest piece. Prerequisite: fix the shared SQS consumer dropping the duplicate-check ID (`pipeline/transport/sqs.py:221-231`). |
| B3 | A resume-only (HITL approval) request is rejected on every queue path | `pipeline/request_handler.py:130, 268` (#862); `SQSHandler.QueueMessageBody.prompt: str` (`deployment/aws/core/sqs_handler.py:56`) for Lambda REST/WS and ECS WS | Accept `resume` with no prompt on every queue path | #862, extended to the SQS paths | **Open, small.** #862 covers only the local queue path; the SQS part is not covered. |
| B4 | No file uploads (multipart) on real brokers (SQS, Kafka, NATS) | `/chat-multipart` only on `in_memory` (`request_handler.py:256-259`); ECS direct mode had it (`containerized/state.tf:35-49`) | Store attachments when the request arrives and put only references on the queue | new issue | **No issue yet.** |
| B5 | Streaming over plain HTTP (SSE) on brokers and ECS | Needs a shared store that can stream chunks: Redis or Valkey only (`request_handler.py:313-325`); ECS streaming goes to WebSocket only (`ecs_io_handler.py:50`) | Document the Redis/Valkey requirement; ECS gets SSE through B2 | docs | **Docs only.** DynamoDB can't stream chunks. |
| B6 | Leaving `execution.mode` unset breaks the queue paths | Lambda raises (`rest_lambda.py:77`); ECS enqueues, then returns 500 and leaves an orphaned run (`request_handler.py:139` vs `:168-169`) | Default `execution.mode` to `rest_sync` (`core/config.py:691`) | removal issue | **Small fix.** |
| B7 | Azure Functions has no queue path | `deployment/azure/akfunction.py:50`; no Azure Service Bus transport | **Recommended:** drop the Azure Functions target. Azure Container Apps already runs the in-memory queue and stays. | decision (related: #480, #512) | **Decision needed.** |
| B8 | GCP Cloud Run runs inline on a broker transport, and ASYNC fails without an `auth_validator` | `deployment/gcp/akcloudrun.py:58-77`, `pipeline/io_handler.py:220-224` | Always start through `IOHandler`; pass `auth_validator` and `handlers` through. Suspected: Cloud Run must keep CPU allocated for the background threads. | removal issue (related: #482) | **Small fix.** |

## Not a blocker today, but a prerequisite

| Risk | Why it matters | Tracking |
| --- | --- | --- |
| The agent can run twice when a message is redelivered | The runner deletes the input message only after sending the reply. A crash in between makes SQS redeliver it, and the agent runs again with duplicate turns. Direct mode never had this; after removal every deployment does. | #440 |

## Definition used

- **Queue mode**: every chat request goes through a queue to an agent runner, on any transport. The single-container **in-memory** queue counts as queue mode and stays. It is what a bare `RESTAPI.run()` starts.
- **Terraform `queue_mode = false`** only means "no SQS, one container". A container running the in-memory queue is still queue mode.
