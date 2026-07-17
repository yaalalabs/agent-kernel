# AK-133: Sandbox capability — Implementation Plan

Ordered breakdown of [spec.md](spec.md) (approved 2026-07-17) into iterations. Each iteration
leaves the branch working and testable; local, dependency-free value lands first (iterations
1–6 give working mode-1/mode-2 sandboxes on CLI/REST), then `ec2_ssm` as a deliberate
**evaluation checkpoint** (iteration 7 — try mode-3 attach against a real instance and assess
before building further), then the AWS plane and remaining providers. The *how* lives in
spec.md — steps below reference its sections.

## Iteration 1: Package skeleton, data types, errors, config

- **Goal:** `agentkernel.sandbox` imports cleanly; the `sandbox:` config section parses with
  defaults, env overrides, and the single-backend sugar; capability stays inert when disabled.
- **Files:** `sandbox/__init__.py`, `sandbox/model.py`, `sandbox/errors.py`;
  `core/config.py` (new `_Sandbox*` classes + root field); `ak-py/pyproject.toml` (extras
  declared up front: `sandbox-docker`, `e2b`, `daytona`, `kubernetes`).
- **Steps:** spec §Data types, §Error handling (hierarchy only), §Config changes.
- **Verify:** `cd ak-py && uv run pytest tests/test_sandbox.py -k "model or config"` (new
  tests: defaults, sugar synthesis, env override, `enabled=False` inertness) + full existing
  suite green.

## Iteration 2: Core interfaces, fake provider, contract suite

- **Goal:** `Sandbox`/`SandboxProvider` ABCs and `PrincipalResolver` exist;
  `FakeSandboxProvider` passes the public `SandboxProviderContract`.
- **Files:** `sandbox/base.py`, `sandbox/principal.py`, `sandbox/testing.py`.
- **Steps:** spec §ABCs (semantics 1–4), §PrincipalResolver, §testing.py contract suite.
- **Verify:** `uv run pytest tests/test_sandbox.py -k "contract or capability"` — capability
  matrix (undeclared ops raise) green against the fake.

## Iteration 3: Manager, sessions, factory, embedded broker

- **Goal:** end-to-end execution in-process: profile routing, sandbox sessions with nv_cache
  registry, policy/principal fail-closed enforcement, `embedded` broker flavor.
- **Files:** `sandbox/manager.py`, `sandbox/factory.py`, `sandbox/broker/base.py`,
  `sandbox/broker/worker.py`, `sandbox/broker/embedded.py`.
- **Steps:** spec §SandboxManager (registry, resolution, namespace isolation, idle-on-touch,
  per_runtime no-pooling rule), §Factory, §Broker (message models, `BrokerWorkerCore` steps
  1–8), §Policy enforcement.
- **Verify:** `uv run pytest tests/test_sandbox.py` — session round-trip across two
  `Runtime.run` turns, unknown-id/cross-session isolation, stale-handle self-heal, factory
  resolution matrix, fail-closed policy/principal tests.

## Iteration 4: Agent surface — system tools and pre-hook wiring

- **Goal:** agents get the five system tools when enabled; task-completion ingestion works;
  the three core wiring points are done (the only core edits in the whole plan:
  `core/tool.py`, `core/runtime.py`; `core/config.py` landed in iteration 1).
- **Files:** `sandbox/tools.py`, `sandbox/hooks.py`; `core/tool.py` (`SystemToolFactory`
  block), `core/runtime.py` (third system pre-hook).
- **Steps:** spec §System tools, §Task-completion ingestion, §Consumer changes.
- **Verify:** `uv run pytest tests/test_sandbox.py -k "tool" tests/test_runtime.py` — tool
  gating on/off, JSON contract, duplicate-completion halt (tool coverage lives in
  `test_sandbox.py` per spec §Testing); existing runtime/guardrail tests green (hook-cache
  reset fixture already covers the third entry).

## Iteration 5: Thread broker flavor + wait-policy promotion

- **Goal:** the default local flavor: broker thread with private event loop, in-memory queues,
  `wait` promotion to `SandboxTask`, completion into the registry, `check_sandbox_task`.
- **Files:** `sandbox/broker/thread.py`; `sandbox/manager.py` (task registry paths).
- **Steps:** spec §Broker flavors (`thread`), §Completion patterns.
- **Verify:** `uv run pytest tests/test_sandbox_broker.py -k "embedded or thread"` — e2e both
  flavors, loop-identity assertion, promotion + late-completion recovery, dedup.

## Iteration 6: Local providers + example

- **Goal:** first real sandboxes: `local_subprocess` (zero-dep) and `docker`; runnable example.
- **Files:** `sandbox/providers/local_subprocess.py`, `sandbox/providers/docker.py`,
  `examples/cli/sandbox/` (demo + README + config.yaml).
- **Steps:** spec §First-party providers (rows + notes for these two).
- **Verify:** `uv run pytest tests/test_sandbox_providers.py -k "subprocess or docker"`
  (real subprocess; mocked docker SDK); manual: `cd examples/cli/sandbox && uv run demo.py`
  with the `local_subprocess` profile.

## Iteration 7: ec2_ssm provider — mode-3 attach checkpoint

- **Goal:** attach-to-existing-runtime working end-to-end against a real EC2 instance via SSM,
  driven from a local (thread-broker) deployment — the checkpoint for evaluating the attach
  model and the identity mapping before further iterations proceed.
- **Files:** `sandbox/providers/ec2_ssm.py`; `examples/cli/sandbox/` extended with an
  `ec2_ssm` profile (`attach_to` fed via `AK_SANDBOX__PROFILES__EC2__EC2_SSM__ATTACH_TO`).
- **Steps:** spec §First-party providers (`ec2_ssm` row + notes: `send_command` +
  `get_command_invocation` polling, `python3 - <<'EOF'` heredoc wrapping, attach-only `create`,
  no-op `destroy`), §PrincipalResolver mapping (agent: default boto3 chain; user:
  `sts:AssumeRole` + SSM `RunAs`).
- **Verify:** `uv run pytest tests/test_sandbox_providers.py -k "ssm"` (mocked boto3: command
  call shapes, heredoc wrapping, AssumeRole/RunAs arguments per identity mode); manual: run the
  example against a real instance (agent runs `run_command`/`run_code` over SSM, reuses the
  same `sandbox_session_id` across turns). **Pause here for evaluation — iterations 8+ proceed
  only after this checkpoint is reviewed.**

## Iteration 8: AWS broker plane — sqs flavor, workers, terraform

- **Goal:** brokered execution on AWS: SQS client flavor, ECS + Lambda workers, DB-first
  completions via the reused `ResponseStore`, session inventory + idle sweep, payload offload,
  `worker_timeout_ceiling` fail-fast, completion events onto the agent input queue.
- **Files:** `deployment/aws/sandbox/{__init__,sqs_broker,ecs_worker,lambda_worker}.py`;
  `deployment/aws/__init__.py` (export `SandboxBrokerRunner`);
  `ak-deployment/ak-aws/common/sandbox_broker/` (module with `mode` variable + the four
  outputs).
- **Steps:** spec §Broker flavors (`sqs`), §Completion delivery, §Broker-side session
  inventory, §Fail-fast timeout ceiling, §Documentation/provisioning (terraform bullet).
- **Verify:** `uv run pytest tests/test_sandbox_broker.py` (stubbed boto3: message schema,
  DB-before-event ordering, emission rule, `on_permanent_failure` → failed completion, offload,
  ceiling rejection); `terraform validate` in the module.

## Iteration 9: Cloud SaaS providers — e2b, daytona

- **Goal:** the two cloud sandbox backends, config-swappable.
- **Files:** `sandbox/providers/e2b.py`, `sandbox/providers/daytona.py`.
- **Steps:** spec §First-party providers (rows + notes); confirm the extras' version floors
  against current SDK releases (flagged in spec §Consumer changes).
- **Verify:** `uv run pytest tests/test_sandbox_providers.py -k "e2b or daytona"` (mocked
  SDKs: call shapes, native idle timeout pass-through, `to_thread` for daytona).

## Iteration 10: Remaining attach-mode / AWS-native providers — kubernetes, bedrock_agentcore

- **Goal:** the remaining mode-3 backend and the AWS-native backend, with both identity modes
  where declared — informed by the iteration-7 checkpoint findings.
- **Files:** `sandbox/providers/kubernetes.py`, `sandbox/providers/bedrock_agentcore.py`.
- **Steps:** spec §First-party providers (rows + notes), §PrincipalResolver mapping table
  (impersonation headers, `sts:AssumeRole`).
- **Verify:** `uv run pytest tests/test_sandbox_providers.py -k "kubernetes or bedrock"`
  (mocked SDKs; principal-mapping arguments asserted per mode).

## Iteration 11: Tests — coverage completion and lint

- **Goal:** the full spec §Testing matrix is present and green; no coverage gaps against the
  design's requirements checklist.
- **Files:** `tests/test_sandbox.py`, `tests/test_sandbox_broker.py`,
  `tests/test_sandbox_providers.py` (fill any assertions not landed with their iteration).
- **Steps:** walk spec §Testing item by item; no existing test file changes (verified in spec
  §Testing — the autouse hook-cache reset in `tests/test_runtime.py:15-23` already
  accommodates the third system pre-hook, and no patch targets move).
- **Verify:** `cd ak-py && uv run pytest` and `make lint-check-all` both clean.

## Iteration 12: Sync docs and skills

- **Goal:** every documentation and skill surface matches the implementation before merge.
- **Files/surfaces:**
  - `docs/docs/advanced/sandbox.md` (new page: capability, config reference with the
    locked-down egress example, profiles, broker flavors per deployment mode, RBAC,
    isolation-tier table).
  - `ak-py/README.md` (config section) and `examples/cli/sandbox/README.md`.
  - `ak-deployment/ak-aws/` README surface for the new `sandbox_broker` module.
  - New dev skill `.agents/skills/ak-dev-new-sandbox-provider/` (clone
    `ak-dev-new-guardrail-provider` structure; provider file → capabilities declaration →
    factory short name → config block → extra → contract tests → example → docs checklist).
  - Skill inventories: `docs/docs/agent-skills.md` (fifteen → sixteen + table row) and
    `docs/specs/agent-skills.md` (table row + directory-tree entry).
  - `.agents/skills/ak-dev-sandbox-research/SKILL.md`: status → implemented; its
    "How to Continue" step 4 (spin off the provider skill) is satisfied by this iteration.
  - `.agents/skills/ak-dev-architecture/SKILL.md`: add the sandbox capability to the
    directory structure and pluggable-capability lists.
  - Verified no-update-needed: integration/messaging skills, framework-adapter skills (no
    adapter code changed), `ak-dev-testing-conventions` (new test files follow existing
    patterns — add rows to its test-file table only).
- **Steps:** run the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch`
  flows over the branch delta as the final pre-merge check.
- **Verify:** both sync flows report no remaining drift; docs site builds.

## Future requirements — where they land (no rework required)

Deferred items from design.md's non-goals, each with its seam:

- **Azure dynamic sessions / Google Vertex AI providers** — new modules under
  `sandbox/providers/` + config block + extra, via the `ak-dev-new-sandbox-provider` skill;
  the narrow-contract core surface was validated against Azure/Bedrock, so no interface change.
- **`k8s_pod` broker flavor (on-premise)** — a new worker entry point reusing
  `BrokerWorkerCore` + a queue transport for the chosen on-prem bus; client stays
  flavor-agnostic via the dotted-path registry.
- **Per-runner reply-to queues** (sync waits at scale on server-based runners) — additive to
  the DB-first contract: a `reply_to` field on `SandboxBrokerRequest` and a dispatcher in the
  runner; completions stay DB-first so nothing else moves.
- **Lambda pre-warming** — terraform-module concern (provisioned concurrency / warmer rule);
  no ak-py change.
- **`per_runtime` pooling / warm-start** — internal to `SandboxManager`/`BrokerWorkerCore`
  behind the existing per-session lock seam (spec §per_runtime concurrency).
- **Streaming output, port exposure, snapshots** — reserved as future optional capabilities:
  new `SandboxCapabilities` flags + optional `Sandbox` methods defaulting to
  `SandboxCapabilityError`, per the established pattern.
