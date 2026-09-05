# #503: Sandbox queue broker: transport-agnostic queue-decoupled sandbox execution (Implementation Plan)

Order of build for [spec.md](spec.md). Each iteration leaves the branch working and testable;
unit tests land with their component (repo convention), and the two consolidated gate
iterations (tests, docs/skills sync) close the story. The two examples and the RBAC
impersonation iteration are deliberately last (design resolutions 2026-08-24).

## Iteration 1: Wire contract and factory seams

- **Goal:** Every foundation the flavor and worker build on exists, with zero behavior change
  for existing callers.
- **Files:** `sandbox/broker/base.py`, `sandbox/broker/worker.py`, `sandbox/model.py`,
  `sandbox/broker/wire.py` (new), `pipeline/transport/base.py`,
  `pipeline/response_store/factory.py`, `pipeline/response_store/{base,in_memory,redis,valkey,dynamodb}.py`,
  `core/config.py`, tests.
- **Steps:**
  1. Add `ExecutionCompletion.error_type`; stamp
     `error_type` in `BrokerWorkerCore.process` (spec §Wire contract).
  2. `SandboxFile` JSON-mode base64 (de)serializers; `sandbox/broker/wire.py` codec.
  3. `QueueTransportFactory` `queues_config` seam;
     `ResponseStoreFactory.create` `response_store_config`/`transport_type`/`ttl` seam
     (spec §Factory seams).
  4. `ResponseStore` scan capability + the four built-in implementations (spec §Idle-session
     sweep).
  5. `_ExecutionBrokerConfig`: add `queue`, `wait_poll_interval`; update the
     `flavor` description; remove `request_queue_url`/`object_store_bucket` (spec §Config).
- **Verify:** `cd ak-py && uv run pytest` fully green (no existing patch targets move); new
  tests: codec round trip with non-UTF-8 bytes, seam default-path parity, scan capability,
  stale removed-field YAML/env keys ignored.

## Iteration 2: The `queue` broker flavor (client)

- **Goal:** `sandbox.broker.flavor: queue` resolves and the client submits, polls, promotes,
  and recovers over the `in_memory` transport.
- **Files:** `sandbox/broker/queue.py` (new), `sandbox/factory.py`,
  `tests/test_sandbox_queue_broker.py` (new), `tests/test_sandbox_broker.py`.
- **Steps:**
  1. `QueueExecutionBroker` per spec §The `queue` broker flavor: fail-fast constructor,
     effective-wait rules (destroy fire-and-forget, bounded `wait=None`),
     ceiling and size guards, send shape, bounded poll with typed re-raise,
     `result()`.
  2. `_BUILTIN_BROKERS["queue"]`; extend the built-in list assertion at
     `test_sandbox_broker.py:356-361`.
- **Verify:** `uv run pytest tests/test_sandbox_queue_broker.py tests/test_sandbox_broker.py`;
  client cases fake the worker by writing completions into the store.

## Iteration 3: The queue broker worker

- **Goal:** A runnable worker consumes requests end to end: the request loop executes and
  queues the record, the output loop persists it, plus truncation, permanent failure, sweep.
- **Files:** `sandbox/broker/queue_worker.py` (new), `sandbox/__init__.py`,
  `tests/test_sandbox_queue_broker.py`.
- **Steps:**
  1. `QueueBrokerWorker.run()` per spec §The queue broker worker: fail-fasts, signal
     discipline, the two `ConsumerLoop`s + sweep task under `ThreadRunner`.
  2. `_process_request` (decode, `core.process`, truncate, output-queue send) with
     `_on_request_permanent_failure` (real/placeholder-session completions to the output
     queue), and `_process_completion` (store write, inventory upsert) with
     `_on_completion_permanent_failure` (ERROR + dead-letter), per spec §Completion delivery
     over the output queue.
  3. Export `QueueBrokerWorker` from `agentkernel.sandbox`.
- **Verify:** end-to-end tests over `in_memory`: round trip, ordering, output-queue delivery
  with store-failure retry that never re-executes, promotion recovery via `task_status` →
  `result()`, permanent failure, truncation, sweep, fail-fasts.

## Iteration 4: The `kubernetes` sandbox provider

- **Goal:** `type: kubernetes` provisions, attaches, executes, and destroys pods (agent-mode
  identity), with honest capabilities and the config-asserted NetworkPolicy.
- **Files:** `sandbox/providers/kubernetes.py` (new), `sandbox/factory.py`, `core/config.py`
  (`_SandboxKubernetesConfig` extensions), `ak-py/pyproject.toml` (`kubernetes` extra),
  `tests/test_sandbox_providers.py`, `tests/test_sandbox.py`.
- **Steps:** spec §The `kubernetes` sandbox provider: handle + provider, pod manifest with
  hardened defaults and policy mapping, instance capability override, attach/destroy, factory
  branch + `_BUILTIN_PROVIDER_NAMES`, config fields.
- **Verify:** `TestKubernetesContract` + provider specifics over the fake SDK
  (`monkeypatch.setitem(sys.modules, "kubernetes", ...)`, the `docker_env` pattern); factory
  resolution and missing-extra tests.

## Iteration 5: Helm chart tier

- **Goal:** `sandboxWorker.enabled: true` deploys the worker with RBAC, KEDA scaling, and
  values-gated namespace hardening; default renders are byte-identical.
- **Files:** `ak-deployment/ak-k8s/chart/values.yaml`, five new templates
  (`deployment-sandbox-worker`, `serviceaccount-sandbox`, `rbac-sandbox`,
  `scaledobject-sandbox`, `sandbox-hardening`), `templates/configmap-env.yaml`,
  `.github/workflows/chart-test.yaml`, `ak-deployment/ak-k8s/README.md` (tier section).
- **Steps:** spec §Helm chart changes; add the `sandboxWorker.enabled=true` +
  `hardening.enabled=true` render to chart-test's explicit-render step.
- **Verify:** `helm template` with defaults diffs clean against pre-change output; enabled
  renders pass; `ct lint --config ak-deployment/ak-k8s/ci/ct.yaml`.

## Iteration 6: Example: `examples/sandbox/broker-kafka` (Kafka shape)

- **Goal:** The #587-shaped topology runs locally: CLI agent over Kafka, worker driving
  kubectl-read-only sandbox pods in kind, RBAC as the boundary.
- **Files:** `examples/sandbox/broker-kafka/*` (spec §Examples), `.github/test-config.yaml`.
- **Steps:** transport-example layout with the `ENTRYPOINTS` dispatch; `k8s/rbac.yaml` binding
  the sandbox-pod SA to `view`; sentinel tests (read-only success within the bounded poll,
  RBAC-rejected write, promoted task recovered via `check_sandbox_task`); README including the
  Lambda-mode (sandbox queues on Kafka, DynamoDB response store) variant section; register as
  `type: containerized`.
- **Verify:** `./build.sh local && uv run pytest -s` with docker + kind + `OPENAI_API_KEY`
  (self-skips otherwise).

## Iteration 7: Example: `examples/sandbox/broker-nats` (NATS chart shape)

- **Goal:** The chart-deployed topology demonstrates the promotion recovery over NATS with the
  hardened image, securityContext, and namespace hardening.
- **Files:** `examples/sandbox/broker-nats/*` (spec §Examples: `app_sandbox_worker.py`,
  `deploy/Dockerfile.sandbox-worker`, sandbox-profile `config.nats.yaml`, chart values overlay,
  README walkthrough).
- **Steps:** build on `examples/k8s/openai-queue-mode`; overlay enables `sandboxWorker` and
  `sandboxWorker.hardening`; README walks submit → turn ends pending → `check_sandbox_task`
  fetches the finished result on the next turn.
- **Verify:** the README walkthrough end to end on a local cluster (k3d/kind); `helm template`
  with the overlay renders clean. Registered in `.github/test-config.yaml` as
  `type: containerized` with a self-skipping `app_test.py` (resolution 2026-09-01).

## Iteration 8: RBAC impersonation (kubernetes user mode)

- **Goal:** `identity.mode: user` profiles run under the invoking user's own RBAC via
  impersonation headers.
- **Files:** `sandbox/providers/kubernetes.py`, `tests/test_sandbox_providers.py`,
  `docs/docs/advanced/sandbox.md` (identity-mapping row).
- **Steps:** spec §RBAC impersonation: per-`(user, groups)` impersonating clients (cached per
  subject), applied to all pod-lifecycle/exec/NetworkPolicy calls; flip
  `capabilities.principal_user` to `True`.
- **Verify:** impersonation-header assertions on every call shape; fail-closed test when the
  resolver yields no user principal (the worker check, no worker change).

## Iteration 9: Tests and quality gates

- **Goal:** The whole story holds together under the repo gates.
- **Steps:** full `cd ak-py && uv run pytest`; `make lint-check-all`; re-run the transport
  contract suites (`tests/test_transport_contract.py`, and the env-gated live file against the
  transport examples' compose stacks) to confirm the factory seams changed nothing; chart lint
  + kind smoke matrix green.
- **Verify:** all of the above green; no existing patch target moved (spec §Testing).

## Iteration 10: Sync docs and skills

- **Goal:** Every guidance surface matches the shipped behavior; run the
  `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` flows before merge.
- **Docs:** `docs/docs/advanced/sandbox.md` (queue flavor, kubernetes provider row,
  RBAC-not-string-parsing guidance, at-least-once and sizing notes, the
  wait-then-`check_sandbox_task` recovery contract); `docs/docs/advanced/queue-mode-guide.md` (cross-reference);
  `ak-py/README.md` (`kubernetes` extra); `ak-deployment/ak-k8s/README.md` (done in
  iteration 5, re-verified here); `examples/sandbox/README.md` index (+2 rows).
- **Skills:** `.agents/skills/ak-dev-architecture/SKILL.md` (sandbox section: `queue` flavor,
  worker, coupling amendment, config fields; pipeline section: factory seams, response-store
  scan capability); `.agents/skills/ak-dev-new-sandbox-provider/SKILL.md` (provider table
  + kubernetes row, instance-capability-override pattern, planned-list update);
  `.agents/skills/ak-dev-new-queue-transport/SKILL.md` (sandbox broker as a second factory
  consumer); user skills under `ak-py/src/agentkernel/skills/` wherever sandbox providers or
  broker flavors are enumerated.
- **No update needed (verify, then state):** the other `ak-dev-new-*` skills,
  `ak-dev-testing-conventions` beyond the new test-file rows, deployment READMEs outside
  ak-k8s, `docs/docs/deployment/onprem-kubernetes.md` unless the sandbox tier is mentioned
  there.
- **Verify:** both sync flows report clean; `make lint-check-all` still green.
