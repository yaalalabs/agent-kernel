# #966: Gap analysis of deferred work across shipped features

Every spec under `docs/specs/` records what its feature left out: non-goals, deferred iterations,
follow-ups and open questions. This document collects those notes from all 53 spec folders, checks
each one against the code and the issue tracker, and lists what is still open. It is the input for
a later step that turns the open items into issues.

- **Baseline:** `develop` at `e1f175513` (v0.10.1), checked on 2026-11-16.
- **Issue tracker snapshot:** 390 issues (119 open) on the same date.

## How this was built

- **Sources read:** the deferral sections of every `design.md`, `spec.md`, `plan.md` and
  `release-notes.md` (Non-goals, Open questions, Deferred follow-ups, Follow-ups, Future
  requirements, post-merge iterations), plus inline mentions of "deferred", "follow-up", "own
  issue", "not implemented" and similar. `research/` folders were not read.
- **Each item was then checked twice:**
  - against the code, to see whether it has since been built;
  - against the open and closed issues, to see whether something already tracks it.
- **What counts as a gap:** something a spec named as left out that a user or maintainer could
  still reasonably expect, and that `develop` does not have.
- **What does not count:**
  - a deliberate, permanent design decision (listed in [Deliberate non-goals](#deliberate-non-goals-not-gaps));
  - an item that has since shipped (listed in [Deferred items that have since shipped](#deferred-items-that-have-since-shipped));
  - round-2 work of a feature that is still in progress (#603, listed in [In flight](#in-flight-603-identity-rbac-and-registry)).

## How to read the tables

- **Source:** path under `docs/specs/`, with the line where the section starts.
- **State on develop:** what the check found. Code paths are under `ak-py/src/agentkernel/` unless
  they start with another top-level folder. "Not re-checked" means the row rests on the spec's own
  statement and nobody has confirmed it in code yet.
- **Tracked by:**
  - `#NNN`: an open issue covers it.
  - `Partly #NNN`: an open issue covers part of it; the row says which part is uncovered.
  - `Related #NNN`: an open issue is close but does not clearly include it.
  - `None`: nothing tracks it.
  - `None (spec promised one)`: the spec said the item would get its own issue or ticket, and no
    such issue exists.

## Summary

| Area | Open gaps | No tracking issue |
| --- | ---: | ---: |
| Sandbox | 11 | 11 |
| Queue pipeline and scaling | 13 | 8 |
| AWS Lambda (serverless) | 7 | 3 |
| GCP and Azure queue mode | 7 | 5 |
| Stores, configuration and secrets | 7 | 7 |
| AG-UI, A2UI, A2A and MCP | 11 | 5 |
| Human in the loop | 8 | 6 |
| Hooks, guardrails and streaming | 5 | 5 |
| Tracing and evaluation | 7 | 7 |
| Realtime voice | 6 | 3 |
| Framework adapters | 4 | 1 |
| Messaging integrations | 5 | 4 |
| Scheduled tasks | 4 | 4 |
| Knowledge base, skills and CI | 6 | 4 |
| **Total** | **101** | **73** |

"No tracking issue" counts rows marked `None` or `None (spec promised one)`. Rows marked `Partly`
or `Related` are counted as tracked.

**Suggested first picks.** This ordering is the author's judgment, not something the specs state.
These are the untracked gaps where a user gets wrong or unsafe behavior with no error:

- **HOOK-2, HOOK-1:** output guardrails and `PostHook.on_run` do not act on streamed replies.
- **STO-2:** `a2a.task_store_type: redis` is accepted but tasks stay in process memory.
- **SBX-1:** container-backed sandboxes can be orphaned when the process exits.
- **TRC-1:** streamed runs produce no session span on any tracer.
- **UI-1:** an AG-UI frontend that sends its own tools gets no error and no tool calls.
- **STO-4:** a thread backend provisioned by Terraform is silently unused when `thread.type` is not set.

## Open gaps by area

### Sandbox

Specs: `494-sandbox-capability`, `503-sandbox-queue-broker`, `692-sandbox-extended-permissions`.

| ID | Gap | Source | State on develop | Tracked by |
| --- | --- | --- | --- | --- |
| SBX-1 | Process-exit cleanup backstop: an `atexit` or signal hook in `SandboxManager` that destroys `per_runtime` sandboxes and leaked `per_session` handles | `494-sandbox-capability/plan.md:194` (iteration 8.5) | No `atexit` or signal handler anywhere under `sandbox/` | None |
| SBX-2 | `bedrock_agentcore` provider | `494-sandbox-capability/plan.md:211` (iteration 10) | `_BUILTIN_PROVIDER_NAMES` is `local_subprocess`, `docker`, `ec2_ssm`, `e2b`, `daytona`, `kubernetes` (`sandbox/factory.py:20`) | None |
| SBX-3 | Azure Container Apps dynamic sessions provider and Google Vertex AI provider (Vertex AI is also unresearched) | `494-sandbox-capability/design.md:374`, `plan.md:253` | Neither exists under `sandbox/providers/` | None |
| SBX-4 | Cloud provisioning for the sandbox broker: an AWS Terraform module (queues, response store, worker compute), and the GCP and Azure equivalents | `494-sandbox-capability/plan.md:178` (iteration 9), `503-sandbox-queue-broker/design.md:323` | No file under `ak-deployment/ak-aws`, `ak-gcp` or `ak-azure` mentions sandbox. The only packaged worker is the Helm chart's `deployment-sandbox-worker.yaml` | None |
| SBX-5 | Object-store offload for results larger than the inline limit | `503-sandbox-queue-broker/design.md:323`, `:345` | `result_ref` is reserved (`sandbox/broker/base.py:61`); the queue worker truncates with a notice ("v1, no offload", `sandbox/broker/queue_worker.py:214`) | None |
| SBX-6 | Re-invoke the agent when a long-running sandbox task completes. #503 removed completion events and said asynchronous resumption would arrive with human in the loop | `503-sandbox-queue-broker/design.md:345` (resolved 2026-08-31) | The contract is still bounded wait plus `check_sandbox_task`; nothing under `sandbox/` re-invokes an agent, although #606 has shipped | None |
| SBX-7 | Streaming execution output, port exposure or preview URLs, and public snapshot, pause and resume | `494-sandbox-capability/design.md:374`, `plan.md:253` | `SandboxCapabilities` has no flag for any of them (`sandbox/model.py:34-50`) | None |
| SBX-8 | `per_runtime` pooling and warm start | `494-sandbox-capability/plan.md:253`, `spec.md:314` | No pooling in `sandbox/manager.py` | None |
| SBX-9 | Provider hardening: wrap raw SDK and OS errors (dead Docker daemon, `mkdtemp` failure) in `SandboxProvisionError` | `494-sandbox-capability/spec.md:798` | `docker.py`, `local_subprocess.py` and `ec2_ssm.py` never raise `SandboxProvisionError`; `kubernetes.py` does | None |
| SBX-10 | Verify that `network_egress: allowlist` is a hard limit on `e2b` and `daytona`, and run both examples in CI | `692-sandbox-extended-permissions/release-notes.md:148`, `design.md:99` | The mapping is implemented (`e2b.py:158`, `daytona.py:198`) but still marked unverified. Both examples are commented out in `.github/test-config.yaml:93-97` until `E2B_API_KEY` and `DAYTONA_API_KEY` secrets exist | None |
| SBX-11 | Broker optimizations: per-runner reply-to queues for synchronous waits at scale, and Lambda worker pre-warming | `494-sandbox-capability/design.md:374`, `plan.md:253` | Not built. Both are additive | None |

### Queue pipeline and scaling

Specs: `401-scalability-design`, `495-onprem-kubernetes`, `524-pluggable-integration-adapter`,
`710-agui-queue-pipeline`, `760-serverless-integrations`, `780-a2a-mcp-queue-pipeline`.

| ID | Gap | Source | State on develop | Tracked by |
| --- | --- | --- | --- | --- |
| PIPE-1 | Application metrics endpoint: a Prometheus `/metrics` surface for retry and permanent-failure counters, redeliveries, turn duration, response-store waits and WebSocket push outcomes | `495-onprem-kubernetes/plan.md:290` | No Prometheus or `/metrics` code in `ak-py/src`. The chart ships a `ServiceMonitor` that stays disabled until the app exposes the path (`ak-deployment/ak-k8s/chart/values.yaml:368-373`) | None (spec promised one) |
| PIPE-2 | Automated end-to-end suite for `examples/k8s/openai-queue-mode` on a kind cluster: multi-turn sessions, retry to permanent failure, a runner restart mid-conversation, the Kafka variant | `495-onprem-kubernetes/plan.md:290` | The example has no `app_test.py` and is not in `.github/test-config.yaml`. Chart lint and a kind install smoke run in `chart-test.yaml` | None (spec promised one) |
| PIPE-3 | Examples restructure for the pipeline era: which example shows what, the posture of the cloud direct-mode examples, naming, shared README conventions | `495-onprem-kubernetes/plan.md:290`, `design.md:350` | Not done | Related #510 |
| PIPE-4 | Session-level message dedup: a message redelivered after a processed-but-not-deleted failure re-runs the agent and appends the turn to history again | `401-scalability-design/design.md:458` | `pipeline/agent_runner.py` only sets dedup ids on output chunks; there is no message-id bookkeeping on the input side | #440 |
| PIPE-5 | Validate the BacklogPerTask scaling policy against a representative workload. It shipped unmeasured | `401-scalability-design/design.md:458` | Not benchmarked | Related #468, #917 |
| PIPE-6 | Helm chart support for the poller tier: a Deployment and a `values.yaml` block for `PollerRunner` | `524-pluggable-integration-adapter/design.md:471`, `plan.md:134` | No poller template under `ak-deployment/ak-k8s/chart/templates/` | None (spec promised one) |
| PIPE-7 | Chunk streaming on the `dynamodb` response store. Without it, an SQS plus DynamoDB app must add Redis or Valkey to run AG-UI or SSE in queue mode | `710-agui-queue-pipeline/design.md:380` | `pipeline/response_store/dynamodb.py` has no `add_chunk`, `stream` or `close_stream`; the base class raises `NotImplementedError` (`base.py:93-99`) | None |
| PIPE-8 | Two repairs #710 left for later: `ResponseStoreFactory` should consult the transport when `in_memory` is configured explicitly, and the `IOHandler` shared-store guard should cover the STREAM route | `710-agui-queue-pipeline/design.md:380` | The factory still short-circuits on an explicit `in_memory` (`pipeline/response_store/factory.py:50-58`). The `IOHandler` guard was not re-checked. The third repair, `SessionStore.shared`, has landed | None (spec promised one) |
| PIPE-9 | Idempotent chunk delivery on the STREAM and SSE route: a redelivered message can replay chunks to the client | `710-agui-queue-pipeline/design.md:380`, `:317` | Not re-checked | None (spec promised one) |
| PIPE-10 | Faster reply pickup for callers that wait on the response store: shorter polls, backoff, or blocking store waits | `780-a2a-mcp-queue-pipeline/design.md:345`, `plan.md:167` | Not re-checked | None (spec promised one) |
| PIPE-11 | ECS runtime classes become pipeline instantiations. This also closes three items other specs parked on it: A2A and MCP in ECS queue mode, the messaging attribute drops in `ECSAgentRunner` and `ECSOutputConsumer`, and AG-UI queue mode on ECS | `495-onprem-kubernetes/plan.md:290`, `780-a2a-mcp-queue-pipeline/design.md:334`, `760-serverless-integrations/design.md:724`, `710-agui-queue-pipeline/design.md:380` | ECS still runs its own copies | #870 |
| PIPE-12 | Multipart and attachment requests on broker transports (SQS, Kafka, NATS, Pub/Sub, Service Bus) | `886-gcp-queue-mode/design.md:226`, `887-azure-queue-mode/design.md:179` | No multipart route off `in_memory` | #871 |
| PIPE-13 | Enforce the SQS limit of 10 message attributes at the producer. The producer budgets bytes, not count | `760-serverless-integrations/design.md:724` | Not re-checked | None |

### AWS Lambda (serverless)

Specs: `760-serverless-integrations`, `527-thread-store-deployment`, `641-execution-mode-message-type`,
`612-chatservice-refactor`.

| ID | Gap | Source | State on develop | Tracked by |
| --- | --- | --- | --- | --- |
| LAM-1 | Gmail (the poller integration) on Lambda: a scheduled `poll_once` entry point and a durable handled ledger | `760-serverless-integrations/design.md:724`, `:850` | `poll_once` exists only in `integration/adapter/poller.py`; no Lambda entry point | None (spec promised one) |
| LAM-2 | Messaging webhooks when the stack runs a WebSocket execution mode. No REST gateway exists in those modes | `760-serverless-integrations/design.md:724`, `:800` | Not built | None (spec promised one) |
| LAM-3 | Other REST handlers on Lambda (schedule, thread, AG-UI). Needs generic route mounting with path parameters | `760-serverless-integrations/design.md:724`, `527-thread-store-deployment/design.md:160` | The schedule example still uses its workaround | Partly #879 (thread routes and path-parameter routing; schedule and AG-UI are uncovered) |
| LAM-4 | Provisioned concurrency for the request-handler and authorizer Lambdas in Terraform | `760-serverless-integrations/design.md:724` | No such variable; it is only described in `ak-deployment/ak-aws/serverless/README.md` | None (spec promised one) |
| LAM-5 | API Gateway HTTP API (v2) events and Lambda Function URL events | `760-serverless-integrations/design.md:724`, `641-execution-mode-message-type/design.md:187` | The stack deploys REST API v1 only | Partly #894 (SSE through response streaming; HTTP API v2 is uncovered) |
| LAM-6 | Conversation-thread recording on the serverless runners | `760-serverless-integrations/design.md:724`, `612-chatservice-refactor/design.md:228` | Not re-checked | Related #879 |
| LAM-7 | A2A and MCP on Lambda through the queue pipeline | `780-a2a-mcp-queue-pipeline/design.md:250` | Not built | #932 |

### GCP and Azure queue mode

Specs: `886-gcp-queue-mode`, `887-azure-queue-mode`, `527-thread-store-deployment`.

| ID | Gap | Source | State on develop | Tracked by |
| --- | --- | --- | --- | --- |
| CLD-1 | WebSocket (`async`) and `realtime` modes in GCP and Azure queue mode. Needs a connection store on Firestore and Cosmos DB, and cross-replica delivery on Azure | `886-gcp-queue-mode/design.md:226`, `887-azure-queue-mode/design.md:179` | `FirestoreSessionStore.get_connection_store` always raises `AKConfigError` (`core/session/firestore.py:114-126`). Cosmos DB was not re-checked | None |
| CLD-2 | Scheduled tasks in GCP and Azure queue mode | `886-gcp-queue-mode/design.md:226`, `887-azure-queue-mode/design.md:179` | `schedule/provider/` has `eventbridge` and `local` only | #921, #952 |
| CLD-3 | Helm chart transport blocks for Pub/Sub (GKE) and Service Bus | `886-gcp-queue-mode/design.md:226`, `887-azure-queue-mode/design.md:179` | Chart values cover `nats`, `kafka` and `sqs` | Partly #922 (Pub/Sub; Service Bus is uncovered) |
| CLD-4 | Live SSE through the Terraform-built GCP API Gateway. Streaming must be enabled at gateway creation and Terraform cannot do that yet | `886-gcp-queue-mode/design.md:190` | Not re-checked | None |
| CLD-5 | Azure Service Bus hardening: a retry backoff on `nack`, separate replica bounds per tier, Premium with a private endpoint | `887-azure-queue-mode/design.md:179` | Not re-checked | None |
| CLD-6 | Azure thread-store provisioning in Terraform | `527-thread-store-deployment/design.md:160` | The store class exists (`integration/thread/store/cosmosdb.py`); nothing under `ak-deployment/ak-azure` mentions threads | None |
| CLD-7 | Response stores on Firestore and Cosmos DB. Both specs skipped them because neither can stream chunks | `886-gcp-queue-mode/design.md:226`, `887-azure-queue-mode/design.md:179` | `pipeline/response_store/` has `in_memory`, `redis`, `valkey` and `dynamodb` | None |

### Stores, configuration and secrets

Specs: `491-valkey-session-store`, `527-thread-store-deployment`, `629-scheduled-tasks`,
`689-security-group-from-outside`, `749-secret-resolution`, `762-a2a-sdk-1x-port`.

| ID | Gap | Source | State on develop | Tracked by |
| --- | --- | --- | --- | --- |
| STO-1 | Valkey as a first-class multimodal attachment store | `491-valkey-session-store/spec.md:173`, `plan.md:271` | `core/multimodal/storage/` has `session_cache`, `in_memory`, `redis` and `dynamodb` | None (spec promised one) |
| STO-2 | A real A2A task store on Redis, and Valkey as an option | `762-a2a-sdk-1x-port/design.md:236`, `491-valkey-session-store/spec.md:173` | `RedisTaskStore` is an empty subclass of `InMemoryTaskStore` (`api/a2a/a2a.py:189-190`). `a2a.task_store_type` accepts `in_memory` or `redis` (`core/config.py:145`), so choosing `redis` silently keeps tasks in process memory | None |
| STO-3 | Schedule stores on Firestore and Cosmos DB, for parity with the thread stores | `629-scheduled-tasks/design.md:205` | `schedule/store/` has `in_memory`, `redis`, `valkey` and `dynamodb`. Needed by #921 and #952 | None |
| STO-4 | A `_ThreadStoreConfig` validator that rejects the in-memory type next to a populated backend block. Today, setting the Terraform flag without declaring `thread.type` runs threads in memory with no error | `527-thread-store-deployment/design.md:90`, `spec.md:394` | No such validator was found near the class (`core/config.py:493`); needs confirming before filing | None (spec promised one) |
| STO-5 | A deployable thread-store example that reads the provisioned store directly to assert auto-creation, ownership, naming, ordering and TTL | `527-thread-store-deployment/plan.md:77`, `spec.md:331` | Only the local FastAPI examples exist (`examples/api/thread-openai`, `examples/api/multimodal/thread-openai`) | None (spec promised one) |
| STO-6 | Accept an externally created security group in the Redis and Valkey Terraform modules | `689-security-group-from-outside/design.md:200` | Neither module's `variables.tf` has a security group input. Left out by an explicit decision at the time | None |
| SEC-1 | Built-in secret providers for AWS Secrets Manager, Azure Key Vault and GCP Secret Manager | `749-secret-resolution/design.md:163`, `886-gcp-queue-mode/design.md:226`, `887-azure-queue-mode/design.md:179` | `secret/providers/` has `env`, `aws_ssm` and `kubernetes`. All three are reachable today only as a bring-your-own provider | None |

### AG-UI, A2UI, A2A and MCP

Specs: `523-ag-ui-support`, `706-a2ui-support`, `762-a2a-sdk-1x-port`, `612-chatservice-refactor`,
`607-hitl-thread-history`.

| ID | Gap | Source | State on develop | Tracked by |
| --- | --- | --- | --- | --- |
| UI-1 | Client-executed tools on AG-UI. A frontend that sends `RunAgentInput.tools` gets no error, and the agent never calls them. The original blocker was that AK could not pause a run and resume it; #606 now provides that | `523-ag-ui-support/design.md:859` | Nothing under `integration/agui/` reads the `tools` field | None |
| UI-2 | `StateDelta` events. Only `StateSnapshot` is emitted | `523-ag-ui-support/design.md:493` | No `StateDelta` anywhere in `ak-py/src` | None |
| UI-3 | Agent-produced images. No adapter builds an `AgentReplyImage`, AG-UI degrades the reply to text, MCP has no `ImageContent` mapping, and messaging integrations send text only | `523-ag-ui-support/design.md:859`, `706-a2ui-support/design.md:959`, `612-chatservice-refactor/design.md:228` | `AgentReplyImage` is defined (`core/model.py:128`) and never constructed in `ak-py/src`; no `ImageContent` in `api/mcp/` | None (spec promised one, for the MCP part) |
| UI-4 | Record AG-UI runs as conversation threads, including pauses and decisions | `523-ag-ui-support/design.md:859`, `607-hitl-thread-history/design.md:188` | Not built | #836 |
| UI-5 | Progressive A2UI: emit `createSurface` early and updates as the model produces them | `706-a2ui-support/design.md:959` | A reply is assembled first and carried whole | #835 |
| UI-6 | A callback path from a rendered A2UI surface back to the agent | `706-a2ui-support/design.md:959` | Not built | #940 |
| UI-7 | Move to A2UI v1.0 | `706-a2ui-support/design.md:1044` | Carried version-agnostically on the v1.0 RC media type | #931 |
| UI-8 | A labelled (A2UI) reply sent to a messaging integration arrives as malformed text. #706 accepted this on the grounds that those surfaces are for text | `706-a2ui-support/design.md:959` | Not re-checked; the response handler has changed since | None |
| A2A-1 | Streaming on A2A (`message:stream`) and on MCP | `762-a2a-sdk-1x-port/design.md:236` | Cards keep `streaming: false` | Partly #196 (MCP; A2A is uncovered) |
| A2A-2 | A2A card for Google ADK agents | `762-a2a-sdk-1x-port/design.md:236` | `get_a2a_card` is still a `TODO` (`framework/adk/adk.py:1197-1202`). #603 replaces every adapter's card with `A2ACardBuilder` (`603-identity-rbac-registry/spec.md:647`) | #603 |
| A2A-3 | Conversation-thread participation for A2A and MCP. #612 deferred it "until they have an identity story", which #603 is now delivering | `612-chatservice-refactor/design.md:228` | Not built | None |

### Human in the loop

Specs: `606-human-in-the-loop`, `607-hitl-thread-history`, `720-microsoft-agents-integration`,
`721-claude-agent-sdk`.

| ID | Gap | Source | State on develop | Tracked by |
| --- | --- | --- | --- | --- |
| HITL-1 | A framework-agnostic way to mark a tool as needing approval in `ToolBuilder` | `606-human-in-the-loop/design.md:937` | `core/tool.py` has no approval flag. Each builder passes its native option: `needs_approval` (OpenAI, Claude), `requires_approval` (Pydantic AI), `require_confirmation` (ADK) | None (spec promised one). Related #486 |
| HITL-2 | Timeouts and automatic decisions for a pause nobody answers | `606-human-in-the-loop/design.md:937` | No expiry logic for pauses in `core/` | None |
| HITL-3 | Resume from surfaces other than REST and AG-UI. On the rest, a paused reply renders as JSON text with no way to answer | `606-human-in-the-loop/design.md:937` | Not built | Partly #609 (messaging; CLI, A2A and MCP are uncovered) |
| HITL-4 | Pause support for CrewAI (through Flows) and smolagents | `606-human-in-the-loop/design.md:937` | `supports_pause` exists on the OpenAI, ADK, LangGraph, Pydantic AI, MAF and Claude runners only | None |
| HITL-5 | Microsoft Agent Framework: free-text questions (`input_required`), hosted-service requests such as OAuth consent, and `Workflow` pauses. Also an open question: scope pause records and the native session per agent instead of per runner | `720-microsoft-agents-integration/design.md:112`, `:120` | Not re-checked | None |
| HITL-6 | Claude Agent SDK production readiness: a credentialed live run of defer and resume, resume across workers, and a policy for transcripts larger than the session backend allows | `721-claude-agent-sdk/design.md:168`, `spec.md:82` | `ak-py/tests/test_claude_hitl_live.py` is opt-in and skipped without credentials | None |
| HITL-7 | Thread history: show failed and rejected turns, and set retention or redaction rules for decision payloads | `607-hitl-thread-history/design.md:188` | Not re-checked | None (spec promised one) |
| HITL-8 | Approver identity and an approval inbox: who may answer a pause, and answering from another session | `606-human-in-the-loop/design.md:937` | #603 adds the check that the resuming principal matches the pause's subject | #610 |

### Hooks, guardrails and streaming

Specs: `670-streaming-post-hooks`, `389-structured-agent-responses`, `526-framework-runtime-context`,
`758-dynamic-run-options`.

| ID | Gap | Source | State on develop | Tracked by |
| --- | --- | --- | --- | --- |
| HOOK-1 | `PostHook.on_run` is never called on a streamed run. #706 also depends on it for incremental delivery of labelled streamed replies | `670-streaming-post-hooks/design.md:357`, `spec.md:270`, `706-a2ui-support/design.md:959` | `core/runtime.py` calls `on_run` only in `run()` (line 455); `stream()` drives `on_stream_event` (line 522) | None (spec promised one) |
| HOOK-2 | Streaming implementations for the three built-in guardrail providers | `670-streaming-post-hooks/design.md:357` | Nothing under `guardrail/` implements `on_stream_event`, so output guardrails do not act on streamed replies | None (spec promised one) |
| HOOK-3 | Structured output on streamed runs. A structured-output agent streams the raw JSON text | `389-structured-agent-responses/ak-63-structured-agent-responses.md:278` | Not re-checked | None |
| HOOK-4 | Hooks and `framework_context` do not apply to agent-to-agent calls inside a framework workflow, only to the top-level run | `389-structured-agent-responses/ak-63-structured-agent-responses.md:278`, `526-framework-runtime-context/design.md:141` | Not re-checked | None |
| HOOK-5 | Strip `RESERVED_RUN_OPTIONS` inside `Runner._native_kwargs`, so a reserved key that bypasses validation is harmless on every adapter | `758-dynamic-run-options/plan.md:156` | `_native_kwargs` copies the options and applies the AK-owned keys, with no strip (`core/base.py:449-462`) | None |

### Tracing and evaluation

Specs: `545-logfire-tracing`, `803-prod-eval`, `526-framework-runtime-context`,
`555-pluggable-test-evaluators`, `773-jev-evaluator`, `606-human-in-the-loop`.

| ID | Gap | Source | State on develop | Tracked by |
| --- | --- | --- | --- | --- |
| TRC-1 | Trace streamed runs. The traced runners override `run()` only, so a streamed run has no "Agent Kernel" span and no `session_id` attribute on any tracer | `545-logfire-tracing/design.md:137`, `803-prod-eval/design.md:520`, `526-framework-runtime-context/design.md:112` | No file under `trace/` overrides `stream` | None |
| TRC-2 | Trace `resume()`. Tracing is not preserved across a human-in-the-loop resume on any framework | `606-human-in-the-loop/design.md:729`, `720-microsoft-agents-integration/design.md:112` | No file under `trace/` overrides `resume` or `resume_stream` | None (spec promised one) |
| TRC-3 | A wrapper span on the OpenLLMetry (Traceloop) runners. Without it `trace.user_input` and `trace.output` are empty when traces are fetched back | `803-prod-eval/design.md:520` | Only `trace/openllmetry/claude.py:48` opens a span | None |
| TRC-4 | Deep LangGraph and smolagents instrumentation under Logfire. Today they get the wrapping span only | `545-logfire-tracing/design.md:137` | `trace/logfire/langgraph.py` and `smolagents.py` contain no instrumentation call | None |
| TRC-5 | Production evaluation phases 2 and 3 as a library capability: pipeline, results store, scheduling. Also the live checks still open: a CI Langfuse project with its secrets, and the Logfire and Traceloop status fields | `803-prod-eval/design.md:520`, `:537`, `plan.md:146`, `:260` | The example is the deliverable. Repository secrets could not be checked from here | None |
| EVAL-1 | Evaluator depth: choosing metrics by config, more than one metric per mode, a per-test rubric, a per-call evaluator override, and tool-call, trajectory, multi-turn, multimodal and dataset-level metrics | `555-pluggable-test-evaluators/design.md:612` | Built-ins are `deepeval`, `opik` and `jev` (`test/test.py:14`); the rest was not re-checked | None |
| EVAL-2 | Let `fallback` mode work with judge-only evaluators, so `jev` is not limited to `mode: llm` | `773-jev-evaluator/design.md:133` | Not re-checked | None |

### Realtime voice

Specs: `405-livekit-realtime-voice`, `809-realtime-multi-agent-handoffs`, `810-native-realtime-agents`.

| ID | Gap | Source | State on develop | Tracked by |
| --- | --- | --- | --- | --- |
| RT-1 | Pre-hooks, post-hooks and guardrails on realtime turns | `405-livekit-realtime-voice/design.md:139`, `810-native-realtime-agents/design.md:111` | Realtime turns bypass `Runtime.run()` and `stream()` | #927, #885 |
| RT-2 | Conversation history across reconnects, saving session state at the end of a call, and `framework_context` on realtime | `405-livekit-realtime-voice/design.md:139`, `:162` | Not built | #928 |
| RT-3 | More than one IO process and Agent Runner replica | `405-livekit-realtime-voice/design.md:162`, `809-realtime-multi-agent-handoffs/design.md:99` | Single replica | #948 |
| RT-4 | Model session limits and server-initiated reconnects: Gemini `GoAway`, session resumption and context window compression, and the 60-minute OpenAI limit. A long call ends with an error chunk | `405-livekit-realtime-voice/design.md:139` | No handling of any of these in `ak-py/src` | None |
| RT-5 | Protocol edge cases on the base path: Gemini `tool_call_cancellation`, an OpenAI `response.done` with a failed or incomplete status reported as done, and no `conversation.item.truncate` on barge-in | `405-livekit-realtime-voice/design.md:139` | No handling in `ak-py/src`. Re-check against the native path from #810, which hands interruption and tools to the SDK | None |
| RT-6 | Open questions left by #809 and #810: an opt-out for showing every agent as a billed participant, reporting real playout to the OpenAI playback tracker, whether a tool call should hold the session lock, and observing or sending text into a call from server code | `809-realtime-multi-agent-handoffs/design.md:107`, `810-native-realtime-agents/design.md:111`, `:124` | Not re-checked | None |

### Framework adapters

Specs: `523-ag-ui-support`, `531-introduce-pydanticai-framework`, `659-824-dependency-workflows`.

| ID | Gap | Source | State on develop | Tracked by |
| --- | --- | --- | --- | --- |
| FW-1 | Streaming for the CrewAI and smolagents adapters | `523-ag-ui-support/design.md:859` | Both `stream()` methods raise `NotImplementedError` (`framework/crewai/crewai.py:416`, `framework/smolagents/smolagents.py:200`) | #880 |
| FW-2 | The Pydantic AI adapter reads the private `agent._instructions` | `659-824-dependency-workflows/plan.md:34` | Still reads it (`framework/pydanticai/pydanticai.py:832`) | None (spec promised one) |
| FW-3 | Make AK work with `openai` 3 (one client per event loop), and open one issue per held-back major version | `659-824-dependency-workflows/plan.md:34`, `design.md:168` | Not re-checked | Related #403 |
| FW-4 | Pydantic AI extras parked at integration time: `pydantic-ai-harness` (revisit at its 1.0) and durable execution | `531-introduce-pydanticai-framework/design.md:231` | Not built | Related #783 (Temporal evaluation) |

### Messaging integrations

Specs: `524-pluggable-integration-adapter`, `590-messaging-integration-e2e-tests`,
`612-chatservice-refactor`, `760-serverless-integrations`.

| ID | Gap | Source | State on develop | Tracked by |
| --- | --- | --- | --- | --- |
| MSG-1 | Streaming replies to messaging platforms | `524-pluggable-integration-adapter/design.md:471` | One text reply per turn | None |
| MSG-2 | Rich replies (media and structured content). Needs an output-queue wire-format change | `524-pluggable-integration-adapter/spec.md:390`, `612-chatservice-refactor/design.md:228` | Replies are stringified for delivery | None |
| MSG-3 | Namespace `session_id` across platforms, so a Telegram chat id cannot collide with a WhatsApp number | `524-pluggable-integration-adapter/design.md:471` | Each platform keeps its bare key | Related #863 |
| MSG-4 | Require webhook verification secrets on the pipeline and on ECS. Lambda already requires them | `760-serverless-integrations/design.md:724` | Not re-checked | None (spec promised one) |
| MSG-5 | Deeper end-to-end assertions. The first cut only checks that a reply arrived and is not the error fallback | `590-messaging-integration-e2e-tests/design.md:155`, `:167` | Still the first cut (`e2e/tests/test_slack.py:68-71`) | None |

Agent-first (outbound-initiated) messaging, also a #524 non-goal, is tracked by #384 and #864 and
is not repeated here.

### Scheduled tasks

Spec: `629-scheduled-tasks`. The GCP and Azure providers are CLD-2 and the store backends are STO-3.

| ID | Gap | Source | State on develop | Tracked by |
| --- | --- | --- | --- | --- |
| SCH-1 | Schedule multipart and attachment requests | `629-scheduled-tasks/design.md:205` | Not re-checked | None |
| SCH-2 | Record scheduled occurrences in conversation threads | `629-scheduled-tasks/design.md:205` | Not re-checked | None |
| SCH-3 | Trigger-time delivery guarantees beyond queue redelivery: retry policies and Scheduler dead-letter queues | `629-scheduled-tasks/design.md:205` | Not re-checked | None |
| SCH-4 | Payload-level scheduling from the CLI, A2A, MCP and the messaging integrations. Today only the agent tools cover those surfaces | `629-scheduled-tasks/design.md:205` | Not re-checked | None |

### Knowledge base, skills and CI

Specs: `553-okf-knowledge-bases`, `246-agent-skills`, `773-jev-evaluator`, `659-824-dependency-workflows`.

| ID | Gap | Source | State on develop | Tracked by |
| --- | --- | --- | --- | --- |
| KB-1 | OKF bundles: concurrency control, versioning or locking on write, and a shared or cross-pod manifest cache for bundles that outgrow `max_concepts` | `553-okf-knowledge-bases/design.md:913` | Not re-checked | None |
| KB-2 | An OKF authoring and enrichment agent, and running Attested Computations through the sandbox | `553-okf-knowledge-bases/design.md:913` | Not built | None |
| SKL-1 | Skill distribution (phase 4): a Copilot Agent Plugin and a Claude marketplace plugin | `246-agent-skills/design.md:132` | Not built | Partly #504 (Claude marketplace; the Copilot plugin is uncovered) |
| SKL-2 | Skill tooling: independent skill versions, keeping user edits on `ak skill update` (it overwrites today, `cli/ak.py:206`), CI validation of skill content, and the `ak --help` config warning | `246-agent-skills/design.md:362` | Only the overwrite behavior was re-checked | None |
| CI-1 | `test-trusted-pr.yaml` does not pass `WALLED_API_KEY`, unlike `test.yaml` | `773-jev-evaluator/spec.md:212` | Confirmed: the key appears in `test.yaml` and not in `test-trusted-pr.yaml` | None |
| CI-2 | Flaky tests recorded during the dependency workflow runs: `kind-smoke (dev)` on NATS, `broker-kafka`, and the answer-matching e2e tests | `659-824-dependency-workflows/plan.md:34` | Not re-checked | Related #776 |

## Deferred items that have since shipped

Listed so that nobody files them again.

| Deferred item | Deferred in | Delivered by |
| --- | --- | --- |
| `ec2_ssm`, `e2b` and `daytona` sandbox providers | `494-sandbox-capability/plan.md:141`, `:166` | Shipped (`sandbox/providers/`) |
| `kubernetes` sandbox provider | `494-sandbox-capability/plan.md:211` | #503 |
| `sqs` and `k8s_pod` broker flavors | `494-sandbox-capability/design.md:374`, `plan.md:178` | Replaced by the transport-agnostic `queue` flavor of #503 and the chart's sandbox worker. Cloud provisioning is still open (SBX-4) |
| User-mode principal through Kubernetes RBAC impersonation | `503-sandbox-queue-broker/design.md:345` | Shipped (`sandbox/providers/kubernetes.py:368-388`) |
| A2A and MCP through the queue pipeline | `495-onprem-kubernetes/plan.md:290` | #780 |
| Messaging integrations as request and response handler pairs | `495-onprem-kubernetes/design.md:350` | #524 |
| Queue mode on GCP and Azure | `629-scheduled-tasks/design.md:205` | #886, #887 |
| A2UI support | `523-ag-ui-support/design.md:859` | #706 |
| AG-UI in queue mode | `523-ag-ui-support/design.md:859` | #710 |
| Post-hooks seeing tool-call events on a stream | `523-ag-ui-support/design.md:325` | #670 |
| Attachment source forms on the thread path | `523-ag-ui-support/design.md:700` | #669 |
| A2UI over A2A (data part, media type, card extension) | `706-a2ui-support/design.md:959` | #762 |
| Replaying a labelled reply from thread history | `706-a2ui-support/design.md:959` | #763 |
| Recording pauses and decisions in threads | `606-human-in-the-loop/design.md:937` | #607 |
| Thread recording for queue-mode runners | `612-chatservice-refactor/design.md:228` | #524 (section 14) |
| A callable form of `run_options` | `754-native-run-options/design.md:306` | #758 |
| Existing consumers reading credentials through `SecretManager` | `749-secret-resolution/design.md:163` | #858 |
| Kubernetes secret provider | `749-secret-resolution/design.md:163` | #640 (`749-2-kubernetes-secret-provider`) |
| Security group reuse for AWS containerized in the test pipeline (phase 2) | `716-reuse-sg-in-integration-test-pipeline/design.md:341` | #823 |
| Teams in the messaging e2e suite | `590-messaging-integration-e2e-tests/design.md:155` | Shipped (`_TeamsConfig` at `core/config.py:336`, `e2e/tests/test_teams.py`) |
| A second and third evaluator backend | `555-pluggable-test-evaluators/design.md:612` | #718 (Opik), #773 (JEV) |
| Valkey thread store | `492-shared-database-drivers/spec.md:419` | #527 |
| Renaming the in-memory thread backend from `memory` | `527-thread-store-deployment/spec.md:386` | Shipped (the default is `in_memory`, `core/config.py:493-494`) |
| Resume-only requests on broker transports | `886-gcp-queue-mode/design.md:226` | #862 |
| Realtime broker examples for SQS, Kafka and NATS | `405-livekit-realtime-voice/design.md:131` | Shipped (`examples/api/livekit-voice/openai/`) |
| `SessionStore.shared` predicate | `710-agui-queue-pipeline/design.md:380` | Shipped (`core/session/base.py:21`) |
| Shared Redis and Valkey response-store class | `710-agui-queue-pipeline/plan.md:127` | Done during the #755 review (`pipeline/response_store/redis_like.py`) |
| Realtime multi-agent handoffs | `405-livekit-realtime-voice/design.md:139` | #809, #810 |

## Deliberate non-goals (not gaps)

The specs ruled these out as design decisions, not as postponed work. They are listed so the reader
can see they were considered. Reopen one only if the reasoning behind it has changed.

- **Sandbox:** PTY or interactive terminals through the broker; command-string allowlisting as a
  security boundary; an audit-only mode; package-name allow and deny lists; installing from URLs or
  VCS; GPU selection, desktop and browser automation; running the agent process itself in a sandbox.
- **Pipeline and deployment:** Kafka share groups; installing cluster-scoped infrastructure from
  the chart; exactly-once delivery; Kafka on the Event Hubs endpoint; a queue path for Azure
  Functions (the target is being retired under #957).
- **Secrets:** store-first resolution; per-key references; JSON-blob secrets; writing or rotating
  secrets from the runtime; reading Secrets through the Kubernetes API; projected volumes, key
  remapping and optional Secrets.
- **Surfaces:** structured replies in the CLI; shipping an A2UI catalog, validator or renderer;
  serving A2A 0.3 clients; the JSON-RPC and gRPC A2A bindings; multi-tenant A2A routes.
- **Run options and config:** per-request run options on the chat envelope; run options from
  `AKConfig`; validating unknown keys against SDK signatures; a deep merge of static and dynamic
  options; unifying the off or disabled semantics across backend factories.
- **Frameworks:** an Anthropic Messages API or Managed Agents adapter; a framework-neutral agent
  definition; wiring `pydantic-evals`; long-lived Claude process pools.
- **Evaluators:** a registry or entry-point mechanism; a public evaluator factory; `DAGMetric`.
- **Threads:** a new message role; replaying thread history into the model; thread recording for
  messaging integrations (the platforms own that history).
- **Tracing:** changing the default `trace.type`; OTel baggage propagation of `session_id`.
- **Storage drivers:** async drivers; unifying the store factories into one registry.

## In flight: #603 identity, RBAC and registry

#603 is still being implemented, so its recorded round-2 items are not counted above. Revisit them
when #603 closes (`603-identity-rbac-registry/design.md:879`, `spec.md:1677`):

- A token vault for refresh tokens and third-party consent, and asynchronous approval (CIBA).
- The token exchange flows (`rfc8693`, `entra_obo`, `id_jag`) and the adapter MCP client header wiring.
- Moving OKF roles and the capability `agents:` scopes onto tool grants.
- Management routes for descriptors and grants, ownership enforcement and a `registry_admin` role.
- An `impersonate` grant.
- Canonical identity for messaging sender ids, and session or thread lookup by user.
- Authenticated extended A2A cards and card signing.
- Authorization engines after `static`: `casbin`, then `openfga`, `cedar` and `authzen`.
- Per-run filtering of the system-prompt text about tools.
- The identity examples (plan iteration 29).

`docs/specs/remove-direct-mode/` holds research only; its work is tracked by #959, #956 and #870.

## Observations on the tracker and the specs

- **Promised issues that were never filed.** 20 rows are marked `None (spec promised one)`. They
  are the cheapest to file, because each spec already wrote down the scope.
- **#486 looks addressed.** `OpenAIToolBuilder` now passes options such as `needs_approval=True`
  through to `function_tool` (`framework/openai/openai.py:971-977`). Worth confirming and closing,
  or re-scoping it to HITL-1.
- **Unchecked checklists in shipped specs.** `491-valkey-session-store/plan.md:287-302`,
  `531-introduce-pydanticai-framework/plan.md:138-153`, `780-a2a-mcp-queue-pipeline/design.md:352-357`
  and `803-prod-eval/plan.md:146-148` still show open checkboxes. They were not checked item by
  item here; most describe work that shipped, so they read as open when they are not.
- **Rows marked "Not re-checked".** 24 rows rest wholly or partly on the spec's statement. Confirm each in
  code before filing an issue for it.

## Suggested grouping into issues

A starting point for the later step, by the author's judgment. One line is one candidate issue.
Every row with no tracking issue appears once. A row that an open issue partly covers appears for
its uncovered part.

| Candidate issue | Rows |
| --- | --- |
| Guardrails and `on_run` on streamed replies | HOOK-1, HOOK-2 |
| Hook coverage: structured output on streams, agent-to-agent calls | HOOK-3, HOOK-4 |
| Trace streamed and resumed runs | TRC-1, TRC-2, TRC-3 |
| Sandbox lifecycle hardening | SBX-1, SBX-9 |
| Sandbox broker provisioning on AWS, GCP and Azure | SBX-4, SBX-11 |
| New sandbox providers | SBX-2, SBX-3 |
| Sandbox large results and long tasks | SBX-5, SBX-6 |
| Sandbox capabilities: streaming, ports, snapshots, pooling | SBX-7, SBX-8 |
| Sandbox CI for `e2b` and `daytona` | SBX-10 |
| Pipeline metrics endpoint | PIPE-1 |
| Kubernetes example e2e suite and poller chart tier | PIPE-2, PIPE-6 |
| Response store: DynamoDB chunk streaming and topology guards | PIPE-7, PIPE-8, PIPE-9, PIPE-10 |
| Gmail and WebSocket-mode webhooks on Lambda | LAM-1, LAM-2 |
| Lambda Terraform: provisioned concurrency and HTTP API v2 | LAM-4, LAM-5 |
| GCP and Azure queue mode: WebSocket modes and live SSE on GCP | CLD-1, CLD-4 |
| Azure follow-ups: thread store Terraform, Service Bus hardening, chart values | CLD-3, CLD-5, CLD-6 |
| Store parity: Valkey attachments, A2A task store, Firestore and Cosmos schedule stores | STO-1, STO-2, STO-3, CLD-7 |
| Thread store: config validator and deployable example | STO-4, STO-5 |
| Cloud secret providers | SEC-1 |
| AG-UI client tools and `StateDelta` | UI-1, UI-2 |
| Image replies end to end | UI-3, MSG-2 |
| A2A streaming and thread participation | A2A-1, A2A-3 |
| HITL: tool approval flag, timeouts, more surfaces and frameworks | HITL-1, HITL-2, HITL-3, HITL-4 |
| HITL per-framework follow-ups | HITL-5, HITL-6, HITL-7 |
| Realtime session limits and protocol edge cases | RT-4, RT-5, RT-6 |
| Messaging: streaming replies, session id namespacing, verification secrets, e2e depth, labelled replies | MSG-1, MSG-3, MSG-4, MSG-5, UI-8 |
| Scheduled tasks follow-ups | SCH-1, SCH-2, SCH-3, SCH-4 |
| Evaluator depth | EVAL-1, EVAL-2 |
| Production evaluation follow-ups | TRC-4, TRC-5 |
| Knowledge base follow-ups | KB-1, KB-2 |
| Skills distribution and tooling | SKL-1, SKL-2 |
| Small fixes | HOOK-5, FW-2, CI-1, PIPE-13, STO-6 |
