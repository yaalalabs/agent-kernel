# #495: Unified queue execution pipeline + on-prem Kubernetes deployment (Implementation Plan)

Ordering follows the review directive: Phase A (iterations 1-5) delivers the spec's refactoring
and a runnable `in_memory` local setup: with the AWS/ECS path protected by an invariant that
**the existing test suite passes unmodified at the end of every Phase A iteration**: and includes
the first documentation updates. Phase B (6-8) adds the broker transports, Phase C (9-10) the
WebSocket delivery and the Helm chart, then cross-cutting tests and the final docs/skills sync.
Spec section references are to `spec.md`.

## Phase A: pipeline refactor + local `in_memory` (AWS untouched)

### Iteration 1: Package skeleton and relocations (shims only)

- **Goal:** `agentkernel/pipeline/` exists; `ThreadRunner`, the response-store family, and the
  WS ABCs live in it; every old import path still works. Zero behavior change.
- **Files:** new `pipeline/__init__.py`, `pipeline/thread_runner.py`,
  `pipeline/response_store/{__init__,base,handler,redis,valkey,dynamodb}.py`,
  `pipeline/ws/base.py`; shims at `deployment/common/{thread_runner,response_store,websocket_service}.py`
  and `deployment/aws/core/response_store/` (spec §1 rule 3).
- **Steps:** 1) move modules verbatim; 2) leave re-export shims; 3) keep
  `deployment/common/__init__.py` exports intact.
- **Verify:** `cd ak-py && uv run pytest`: full suite green with **no test edits**
  (`test_thread_runner.py`, `test_akresponsehandler.py` import through the shims).

### Iteration 2: Envelope, transport ABCs, `ConsumerLoop`, ECS shim

- **Goal:** the generic consumer machinery exists and `ECSSQSConsumer` runs on it with an
  unchanged public surface.
- **Files:** `pipeline/envelope.py`, `pipeline/transport/{__init__,base}.py`,
  `pipeline/consumer.py` (§2, §3); rewrite of
  `deployment/aws/containerized/core/sqs_consumer.py` internals (§3).
- **Steps:** 1) `QueueMessage` + attribute constants; 2) `QueueTransport`/`TransportConsumer`
  ABCs + `QueueTransportFactory` skeleton (`resolve_type`, error paths; only dotted-path/`sqs`
  resolution stubs: no concrete transports yet); 3) `ConsumerLoop` with the four semantics rules
  of §3; 4) ECSSQSConsumer classmethods delegate to a `ConsumerLoop` via the raw-record adapter.
- **Verify:** new `test_pipeline_consumer_loop.py`;
  `test_ecs_sqs_consumer_parallel.py` passes **unmodified** (the AWS-protection gate).

### Iteration 3: `in_memory` transport, `in_memory` response store, config

- **Goal:** the default transport and store exist with full queue-semantics parity, selectable
  via config; nothing consumes them yet.
- **Files:** `pipeline/transport/in_memory.py` (§4), `pipeline/response_store/in_memory.py`
  (§10), `core/config.py` (`_QueuesConfig.type` + `_InMemoryQueueConfig`, response-store pattern
  + `IN_MEMORY` enum member, §11).
- **Steps:** 1) `_InMemoryQueue` (per-group FIFO, ack_wait redelivery, dedup window, blocking
  fetch); 2) `InMemoryResponseStore` (record shape, `status_code` retention, chunk streaming);
  3) config fields + `resolve_type()` compat rule (`url` ⇒ `sqs`, else `in_memory`).
- **Verify:** `test_pipeline_in_memory_transport.py`, `test_response_store_in_memory.py`,
  `test_transport_contract.py` (contract vs `in_memory`); `test_config.py` extended for the new
  fields; full suite green.

### Iteration 4: Pipeline components + single-process topology (local runnable)

- **Goal:** `RESTAPI.run()` on a laptop boots the five-component pipeline over `in_memory`
  queues: `rest_sync` (and `mode=None`), `rest_async` poll, SSE streaming, and multipart all
  behave wire-identically to today's direct mode.
- **Files:** `pipeline/{agent_runner,response_handler,request_handler,io_handler}.py` (§8);
  `deployment/common/rest_handler.py` (only the `_build_sync_response` seam);
  `api/http.py` (the three-condition delegation guard: `cls is RESTAPI`, no handlers,
  resolved `in_memory`).
- **Steps:** 1) `AgentRunner`/`StreamAgentRunner` incl. `STATUS_CODE` attribute;
  2) `ResponseHandler` incl. the in_memory STREAM chunk path; 3) `RequestHandler` (enqueue/poll/
  SSE/multipart-on-in_memory, `status_code` → `HTTPException`); 4) `IOHandler` single-process
  topology + startup fail-fast checks (§10); 5) `RESTAPI.run()` guard.
- **Verify:** `test_pipeline_agent_runner.py`, `test_pipeline_response_handler.py`,
  `test_pipeline_request_handler.py` (TestClient end-to-end parity assertions),
  `test_api_http.py` delegation case; run `examples/api/openai` unchanged against the pipeline;
  full suite green.

### Iteration 5: Phase A documentation

- **Goal:** the shipped local behavior is documented before broker work starts.
- **Note:** during the iteration 4 wrap-up, `examples/api/openai` gained explicit queue
  configurability (commented `execution`/`queues.type: in_memory` config block, README
  walkthroughs for rest_sync/rest_async/stream): since every bare-`RESTAPI.run()` example runs
  the pipeline, a separate "queue-mode" example would have been misleading. Verified live against
  OpenAI in all three modes plus the example's own test suite (incl. multipart image/PDF through
  the queue); the docs below should reference it.
- **Files:** `docs/docs/advanced/queue-mode-guide.md` (pipeline framing + `in_memory` section;
  transport matrix marked "SQS via ECS today, kafka/nats upcoming"),
  `docs/docs/deployment/local.md`, `docs/docs/deployment/overview.md`,
  `.agents/skills/ak-dev-architecture/SKILL.md` (pipeline section), `README.md` (local queue
  mode); `docs/specs/495-onprem-kubernetes/` design/spec updated for anything Phase A changed.
- **Steps:** follow the `ak-dev-sync-docs-from-branch` / `ak-dev-sync-skills-from-branch` flows
  scoped to the Phase A diff.
- **Verify:** docs build; skill/doc claims spot-checked against the merged code.

## Phase B: broker transports

### Iteration 6: SQS transport

- **Goal:** the pipeline runs the two-process topology on SQS; wire format interoperates with
  the ECS classes (which remain untouched).
- **Files:** `pipeline/transport/sqs.py` (§5).
- **Steps:** send via `SQSHandler.send_message`; consumer envelope mapping; `AgentRunner.run()` /
  `IOHandler.run()` two-process dispatch.
- **Verify:** `test_pipeline_sqs_transport.py` (incl. kwargs equality with
  `SQSHandler.build_send_message_kwargs`); contract suite vs mocked SQS; full suite green.

### Iteration 7: Kafka transport

- **Goal:** `type: kafka` works end to end with bounded retry, DLQ, and dedup.
- **Files:** `pipeline/transport/{kafka,bookkeeping}.py` (§6), `core/config.py`
  (`_KafkaQueueConfig`), `ak-py/pyproject.toml` (`kafka` extra).
- **Steps:** producer/consumer per §6; `BookkeepingStore` resolved from the `session:` config
  (in_memory fallback WARNING); seek+pause retry; DLQ produce on permanent failure.
- **Verify:** `test_pipeline_kafka_transport.py` (faked clients); contract suite behind a local
  Kafka container (marked integration).

### Iteration 8: NATS JetStream transport

- **Goal:** `type: nats` works end to end; recommended-default posture in config/docs samples.
- **Files:** `pipeline/transport/nats.py` (§7), `core/config.py` (`_NatsQueueConfig`),
  `pyproject.toml` (`nats` extra).
- **Steps:** `_NatsLoop` bridge; partitioned streams/consumers + subject transform;
  `auto_provision` create/verify; ack/nak/term mapping.
- **Verify:** `test_pipeline_nats_transport.py`; contract suite behind a local `nats-server`
  container (integration).

## Phase C: WebSocket delivery and Kubernetes

### Iteration 9: Pod-direct WebSocket delivery

- **Goal:** ASYNC/STREAM modes work on the pipeline: in-process locally, pod-to-pod on
  multi-pod deployments.
- **Files:** `pipeline/ws/{registry,handler,endpoint,push}.py` (§9), `core/config.py`
  (`push_auth_token`, `push_port`), `io_handler.py` (WS-mode mounting + auth fail-fast).
- **Steps:** native `/ws` route + custom-route decorator; `LocalConnectionRegistry`;
  `/internal/push` with shared-secret auth; `PodPushWebSocketHandler`; `ENDPOINT_URL`
  construction (`AK_POD_IP`) + `local` sentinel.
- **Verify:** `test_pipeline_ws.py`; single-process ASYNC/STREAM end-to-end over `in_memory`.

### Iteration 10: Helm chart + k8s example

- **Goal:** `helm install` deploys the two-Deployment topology on a micro-cluster in both
  flavors' values files.
- **Files:** `ak-deployment/ak-k8s/` (§13, incl. observability README section §15),
  `examples/k8s/openai-queue-mode/` (§14), chart-publish workflow addition.
- **Steps:** chart templates + values files; NACK/Strimzi CRs; KEDA ScaledObject;
  NetworkPolicy + push-token Secret; example apps/Dockerfiles/README (k3d/microk8s/k3s paths).
- **Verify:** `ct lint`; kind install with `values-dev.yaml` + one chat request through NATS;
  manual k3d walkthrough of the example README.

## Iteration 11: Cross-cutting tests and CI

- **Goal:** the spec's Testing section is fully realized where it spans iterations.
- **Files:** `.github/workflows/` (integration job running the transport contract against real
  Kafka/NATS containers; kind chart smoke), any remaining contract gaps.
- **Steps:** wire `QueueTransportContract` into integration CI; add the chart smoke job per
  flavor values file.
- **Verify:** CI green on a PR touching the pipeline; `uv run pytest` + `make lint-check-all`.

## Iteration 12: Sync docs and skills (final)

- **Goal:** every documentation and skill surface matches the shipped behavior.
- **Files:** `docs/sidebars.js:61-90` (On-Prem/Kubernetes category), new
  `docs/docs/deployment/onprem-kubernetes.md`, `queue-mode-guide.md` final transport matrix +
  K8s column (`:353` status table), `deployment/overview.md`, deployment READMEs,
  `.agents/skills/ak-dev-architecture` (final), new `.agents/skills/ak-dev-new-queue-transport`
  skill, `README.md` deploy table row.
- **Steps:** run the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` flows
  over the full branch diff; confirm surfaces that need **no** update (serverless docs, Azure/GCP
  pages) and state so in the PR.
- **Verify:** docs build; `ak-dev-review-pr` spec-vs-implementation pass on the final PR.

## Deferred follow-ups (post-#495, separate issues)

- **Examples restructure and update pass**: bring the whole examples tree in line with the
  pipeline era (which examples demonstrate what, cloud direct-mode examples' posture toward the
  in-process pipeline, naming, shared README conventions). Decided 2026-08-13: not part of this
  issue; start only after the #495 implementation (all iterations above) is complete.
- **A2A/MCP uniformity over the pipeline**: A2A and MCP currently execute via `AgentService`
  inline even when their host process runs the pipeline; making them uniform is a separate
  design/issue (decided 2026-08-13).
- **ECS runtime classes become pipeline instantiations**: `ECSAgentRunner`/
  `ECSStreamAgentRunner`/`ECSOutputConsumer`/`ECSIOHandler` still parallel the pipeline's
  `AgentRunner`/`ResponseHandler`/`IOHandler` instead of instantiating them. The wire formats
  already interoperate (spec §5), but the migration carries behavioral decisions (ECS
  error-body-with-200 vs the pipeline's status mapping, API Gateway WS delivery vs
  pod-direct), so it is its own design + issue after #495 (decided 2026-08-14).
  `ECSQueueRequestHandler` and `ECSSQSConsumer` are already thin instantiations.
