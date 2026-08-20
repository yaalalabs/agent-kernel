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
- **Verify:** `test_pipeline_kafka_transport.py` (fake in-memory cluster) +
  `test_pipeline_bookkeeping.py`; the `QueueTransportContract` runs against the fake in-repo.
- **Also delivered:** `examples/transport/kafka/` (two-process pipeline over a single-broker KRaft
  stack) with `kafka_tester.py`, a lightweight harness that runs the compose stack, provisions the
  topics Agent Kernel deliberately does not create, and inspects/produces to topics; its
  `app_test.py` covers rest_sync, a multi-turn session, topic/header flow, and the retry-to-DLQ
  path against a real broker. **Not yet wired into CI**: registering it in
  `.github/test-config.yaml` belongs to iteration 11, and needs the `kafka` extra to be resolvable
  (published release or the locally built wheel via `./build.sh local`).

### Iteration 8: NATS JetStream transport

- **Goal:** `type: nats` works end to end; recommended-default posture in config/docs samples.
- **Files:** `pipeline/transport/nats.py` (§7), `core/config.py` (`_NatsQueueConfig`),
  `pyproject.toml` (`nats` extra).
- **Steps:** `_NatsLoop` bridge; partitioned streams/consumers + subject transform;
  `auto_provision` create/verify; ack/nak/term mapping.
- **Verify:** `test_pipeline_nats_transport.py` (fake JetStream behind the real `_NatsLoop`
  bridge) plus the `QueueTransportContract` with no skips, since `ack_wait` gives NATS a genuine
  visibility timeout. Shipped deviations from the §7 sketch, both recorded there: partitioning is
  computed client-side with a stable `crc32` (no server-side subject transform, so
  `auto_provision: false` operators need no transform in their NACK CRs), and `ack_wait` defaults
  to 300 s rather than 30 s because it is the visibility timeout and a turn that outlives it is
  executed twice.
- **Also delivered:** `examples/transport/nats/` (two-process pipeline over a single-server
  JetStream stack) with `nats_tester.py`, which brings up the stack, waits on a real JetStream
  account lookup, and inspects streams with direct gets rather than a second consumer (a work-queue
  stream rejects overlapping consumers, and a peeking consumer would steal work). Its `app_test.py`
  covers rest_sync, a multi-turn session, stream and per-partition consumer provisioning, and the
  retry-to-termination path. **Verified against a real single-server JetStream stack**: the
  `QueueTransportContract` passed 10/10 with no skips (`ack_wait` is a genuine visibility timeout, so
  the unacked-redelivery case applies here where it does not on Kafka) and the example's own suite
  passed 4/4 with a live agent, exercising `auto_provision` against the server.

## Phase C: WebSocket delivery and Kubernetes

### Iteration 9: Gateway-tier WebSocket delivery (reworked 2026-08-18)

- **Goal:** ASYNC/STREAM modes work on the pipeline through a dedicated WebSocket Gateway:
  co-hosted in-process locally, its own Deployment on multi-pod topologies; the IO handler's
  API stays plain REST.
- **Files:** `core/session/base.py` (`WSConnectionStore` ABC +
  `SessionStore.get_connection_store`), per-store implementations
  (`core/session/redis_like.py`, `in_memory.py`, `dynamodb.py`),
  `core/util/driver/redis_like.py` (`hdel`/`hgetall`) and `dynamodb.py`
  (`query_items`/`query_index`), `pipeline/ws/{registry,handler,endpoint,push,gateway}.py`
  (§9), `core/config.py` (`push_auth_token`, `push_port`, `session.connection_store`),
  `io_handler.py` (broker: REST-only + push-token/shared-store fail-fasts; in_memory: gateway
  co-hosting).
- **Steps:** session-backed connection stores (`get_connection_store` per backend, incl.
  DynamoDB against an existing `session.connection_store.table_name` table); native `/ws`
  route + custom-route decorator enqueueing directly to the transport; `WebSocketGateway.run`
  entry point (broker-only: on `in_memory` it fails fast, naming the co-hosted `IOHandler`
  topology); `/internal/push` (`PostToConnection` analogue) with shared-secret auth;
  store-lookup delivery in `PodPushWebSocketHandler`; `USER_ID` presence replaces
  `ENDPOINT_URL` stamping as the WS-entered discriminator.
- **Verify:** `test_pipeline_ws.py` + `test_session_kv_table.py`; single-process ASYNC/STREAM
  end-to-end over `in_memory`; a two-"pod" delivery test (two registries/gateway apps, reply
  landing wherever the user's connections are).
- **History:** first delivered 2026-08-18 as pod-direct push (design Q3 Option D: `endpoint_url`
  stamped on messages, pod-local registry only, origin-pod-only delivery). Reworked the same
  day, pre-commit, after the maintainer revised Q3 to the gateway model (see design.md): the
  stamped-address plumbing (`pod_endpoint_url` on the enqueue path, endpoint-attribute routing
  in the Response Handler, the endpoint requirement in `StreamAgentRunner`) is replaced by the
  shared connection store, and IOHandler's WS mounting narrows to the `in_memory` co-hosting
  case. Refined 2026-08-19 on maintainer review: the connection store became a per-backend
  `WSConnectionStore` family provided by `SessionStore.get_connection_store()` (any database
  with a driver can implement one; the `KeyValueTable` shim remains only for bookkeeping), the
  gateway entry point stays broker-only (an implicit `in_memory` delegation to the
  single-process topology was tried and reverted the same day: rejection is cleaner, and the
  error names `IOHandler.run(auth_validator=...)` for local testing).

### Iteration 10: Helm chart + k8s example

- **Goal:** `helm install` deploys the io + agent-runner topology (plus the ws-gateway
  Deployment in WS-mode values) on a micro-cluster in both flavors' values files.
- **Files:** `ak-deployment/ak-k8s/` (§13, incl. observability README section §15),
  `examples/k8s/openai-queue-mode/` (§14), chart-publish workflow addition.
- **Steps:** chart templates + values files; NACK/Strimzi CRs; KEDA ScaledObject;
  NetworkPolicy + push-token Secret; example apps/Dockerfiles/README (k3d/microk8s/k3s paths).
- **Verify:** `ct lint`; kind install with `values-dev.yaml` + one chat request through NATS;
  manual k3d walkthrough of the example README.
- **Shipped deviations, all recorded in spec §13's tree:** the NACK CRs are gated by their own
  `natsResources.enabled` rather than `nats.enabled` (the subchart flag also covers dev installs
  running `auto_provision` with no NACK controller, where rendering CRs would fail the install),
  and carry no subject transform per iteration 8's client-side partitioning; the io tier's plain
  HPA (design R10) lives in its own `hpa-io.yaml`; the kind smoke values live in `chart/ci/`
  where chart-testing discovers them. The chart also grew per-component image overrides
  (`ioHandler.image` / `agentRunner.image` / `wsGateway.image` over a shared `image` block)
  because the example bakes one Dockerfile per component, mirroring its ECS counterpart; and the
  example's `deploy/package.sh` cross-installs Linux wheels via uv's `--python-platform`
  (manylinux_2_28 floor: confluent-kafka ships no older-tagged wheels), so the images build from
  macOS hosts too.
- **Verified 2026-08-20:** `ct lint` green (`ci/ct.yaml`); all four values files template
  cleanly against the pinned subcharts (valkey 0.11.0, nats 2.14.5, whose strict values schema
  accepts the condition keys); `helm install` of `values-dev.yaml` + the kind smoke values on a
  fresh kind cluster went ready on the first `--wait`, with the runner auto-provisioning the
  4-partition streams at startup; and two live `rest_sync` chat turns round-tripped
  REST -> NATS -> agent-runner (OpenAI, triage handoffs to the history and math agents) ->
  NATS -> Valkey response store -> the waiting request, with session continuity across the
  turns. The k3d walkthrough of the example README remains the manual gate (kind covered the
  same import-and-install flow in its place).
- **Extended 2026-08-20 (maintainer request):** the example gained the WebSocket tier before
  iteration 11: `app_ws_gateway.py` (the AWS example's demo JWT validator behind
  `WebSocketGateway.run`), a third image in `package.sh`, a `ws_client.py` demo client, and a
  stream-mode README walkthrough (spec §14 updated). Verified live on a fresh kind install with
  `execution.mode=stream` + `wsGateway.enabled`: the client's chat frame was acknowledged with
  `CHAT_QUEUED`, then ~80 `STREAM_CHUNK` token deltas arrived ending in `done: true`, each
  pushed gateway -> NATS -> runner -> NATS -> Response Handler -> `/internal/push` on the
  owning gateway pod, resolved through the Valkey-backed connection store.

## Iteration 11: Cross-cutting tests and CI

- **Goal:** the spec's Testing section is fully realized where it spans iterations.
- **Files:** `.github/workflows/` (integration job running the transport contract against real
  Kafka/NATS containers; kind chart smoke), any remaining contract gaps.
- **Steps:** wire `QueueTransportContract` into integration CI; add the chart smoke job per
  flavor values file.
- **Verify:** CI green on a PR touching the pipeline; `uv run pytest` + `make lint-check-all`.
- **Delivered 2026-08-20:** `ak-py/tests/test_transport_contract_live.py` runs the unchanged
  `QueueTransportContract` against real brokers, env-gated (`AK_TEST_NATS_URL` /
  `AK_TEST_KAFKA_BOOTSTRAP`; skipped in normal runs) with per-test unique streams/topics for
  isolation on a shared broker; a `transport-integration-tests` job in `test-reusable.yaml`
  starts the transport examples' compose stacks (broker services only) and runs it on every PR;
  and `chart-test.yaml` (path-filtered) runs `ct lint`, renders every flavor and optional tier,
  then kind-smokes each flavor values file with one real chat request through NATS: dev
  auto-provisions, while baremetal and eks install the Gateway API v1.6.0 CRDs and a real NACK
  controller so `autoProvision: false` verifies operator-reconciled objects; the CI overlays in
  `ak-deployment/ak-k8s/ci/` swap only storage class and sizing. The transport examples'
  `test-config.yaml` registration (deferred from iterations 7/8) was found already landed.
- **Findings pinned in the live-contract file:** the NATS per-partition pull window
  (`fetch_wait / partitions`) must stay below `ack_wait` or the server redelivers an in-flight
  message into the still-open pull, duplicating it within one fetch (found live, invisible on
  the fake); the contract's fixed group ids need partition counts chosen from the real
  partitioner mappings (crc32 % 4 for NATS; Kafka's murmur2 needs 8, since 4 collides s1 with
  s2); Kafka topic creation polls metadata before use since the pipeline never auto-creates.
- **Verified 2026-08-20 locally:** live contract green twice against real single-node
  JetStream and KRaft brokers (19 passed, 1 justified Kafka timeout_redelivery skip, ~88 s);
  baremetal and eks flavor smokes end to end on kind (NACK reconciled 2 Streams + 8 Consumers
  to Created, Gateway/HTTPRoute applied unreconciled, live chat replies through NATS), dev
  flavor already verified in iteration 10; full `uv run pytest` green apart from the
  pre-existing `test_cli_tester.py` OPENAI_API_KEY dependence (passes with the key, which CI
  sets); `make lint-check-all` green. The workflow runs themselves become observable on the
  next PR touching the pipeline.

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
- **Delivered 2026-08-20 (docs):** new `docs/docs/deployment/onprem-kubernetes.md` under a new
  sidebar On-Prem / Kubernetes category; `deployment/overview.md` gained the flavor node,
  execution-mode/protocol/comparison rows, a Kubernetes column in the queue-topology role
  table, a Getting Started subsection, and corrected WS-delivery claims;
  `queue-mode-guide.md`'s status table row flipped to shipped and the NATS section points at
  the chart and the k8s example; `architecture/overview.md`, root `README.md` (feature bullet
  + deploy-table row), `ak-py/README.md` (On-Prem / Kubernetes deployment section),
  `deployment/local.md`, and the landing page's deploy blurb dropped their stale "upcoming"/
  Docker-only claims. Surfaces confirmed needing no update: the AWS/Azure/GCP
  serverless/containerized pages (Terraform paths unchanged) and `DEVELOPER_GUIDE.md`.
- **Delivered 2026-08-20 (skills):** new `ak-dev-new-queue-transport` dev skill (semantics
  contract, implementation rules from the shipped transports, factory/config/extras, the
  three test layers incl. the live-broker traps, example and chart wiring);
  `ak-dev-architecture` updated (Phase C status, description keywords) and cleaned of
  unresolved stash-conflict markers that had been committed into its pipeline tables (both
  blocks resolved to the side matching the shipped code); `ak-dev-testing-conventions` gained
  the seven missing pipeline/WS/contract test-file rows and the `transport-integration-tests`
  + `chart-test.yaml` workflow entries; user skill `ak-cloud-deploy` gained the On-Prem /
  Kubernetes deployment path (entry files, image contract, helm install per flavor, WS mode,
  teardown) plus a `deploy-kubernetes-helm` eval; inventories updated in
  `docs/docs/agent-skills.md` and `AGENTS.md`.
- **Verified 2026-08-20:** the docs site builds green with the new page and sidebar (Docusaurus
  link checking on); `ak-cloud-deploy` evals JSON re-parses; no em dashes introduced. The
  `ak-dev-review-pr` spec-vs-implementation pass runs on the final PR once pushed.

## Deferred follow-ups (post-#495, separate issues)

- **Examples restructure and update pass**: bring the whole examples tree in line with the
  pipeline era (which examples demonstrate what, cloud direct-mode examples' posture toward the
  in-process pipeline, naming, shared README conventions). Decided 2026-08-13: not part of this
  issue; start only after the #495 implementation (all iterations above) is complete.
- **A2A/MCP uniformity over the pipeline**: A2A and MCP currently execute via `AgentService`
  inline even when their host process runs the pipeline; making them uniform is a separate
  design/issue (decided 2026-08-13).
- **App metrics endpoint for the pipeline**: a Prometheus `/metrics` surface (optional extra,
  `observability.metrics` config) covering what neither the broker exporters nor the tracing
  providers can see: ConsumerLoop retry/permanent-failure counters, redeliveries, per-agent turn
  duration, response-store wait times, WS push outcomes. The io handler and gateway add a route
  to their existing FastAPI apps; the agent-runner, which has no HTTP server, needs a small
  dedicated metrics listener plus chart-side PodMonitor/metrics-port wiring (the chart's
  ServiceMonitor template already exists, disabled and documented as awaiting this). Keep label
  cardinality bounded (per-agent yes, per-session/request no). A neutral pipeline feature, so
  ECS deployments gain it too; the R11 recipes-not-bundled-stack posture is unchanged. Decided
  2026-08-20: post-#495, its own issue.
- **Automated k8s end-to-end test suite**: bring the k8s example up to the transport examples'
  testing bar. Iteration 11's CI covers the chart-level smoke (ct lint/install per flavor values
  file plus one chat request); this task adds an `app_test.py`-style suite for
  `examples/k8s/openai-queue-mode` in the built-in Test framework, registered in
  `.github/test-config.yaml`, driving the chart-deployed topology on an ephemeral kind cluster:
  multi-turn sessions, the retry-to-permanent-failure path through the deployed pods, rollout
  behavior (a runner restart mid-conversation), and the Kafka variant behind the Strimzi
  operator where CI capacity allows. Needs the same release-or-local-wheel resolvability the
  transport examples' registration waits on. Decided 2026-08-20: post-#495, its own issue.
- **ECS runtime classes become pipeline instantiations**: `ECSAgentRunner`/
  `ECSStreamAgentRunner`/`ECSOutputConsumer`/`ECSIOHandler` still parallel the pipeline's
  `AgentRunner`/`ResponseHandler`/`IOHandler` instead of instantiating them. The wire formats
  already interoperate (spec §5), but the migration carries behavioral decisions (ECS
  error-body-with-200 vs the pipeline's status mapping, API Gateway WS delivery vs
  pod-direct), so it is its own design + issue after #495 (decided 2026-08-14).
  `ECSQueueRequestHandler` and `ECSSQSConsumer` are already thin instantiations.
