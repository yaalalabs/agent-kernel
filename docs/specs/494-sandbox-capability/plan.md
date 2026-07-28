# #494: Sandbox capability — Implementation Plan

Ordered breakdown of [spec.md](spec.md) (approved 2026-07-17) into iterations. Each iteration
leaves the branch working and testable; local, dependency-free value lands first (iterations
1–6 give working mode-1/mode-2 sandboxes on CLI/REST), then `ec2_ssm` as a deliberate
**evaluation checkpoint** (iteration 7 — try mode-3 attach against a real instance and assess
before building further), then the AWS plane and remaining providers. The *how* lives in
spec.md — steps below reference its sections.

> **Sequencing change (2026-07-21).** Iterations 1–6 are complete and are being shipped as a
> self-contained first release: working `local_subprocess`/`docker` sandboxes on CLI and REST,
> the thread/embedded brokers, the pluggable factory, and the CLI + API examples. To merge that
> now, the documentation + skills sync (originally iteration 12) is **brought forward** and
> scoped to the implemented surface, followed by a **merge checkpoint**. See
> [Pre-merge: documentation + skills sync](#pre-merge-documentation--skills-sync-brought-forward)
> and [Merge checkpoint](#merge-checkpoint) below. Iterations 7–11 and the remaining
> documentation surfaces (AWS broker plane, the not-yet-landed providers) are taken up after
> this merge; each carries its own doc/skill updates per its iteration.

## Iteration 1: Package skeleton, data types, errors, config

- **Goal:** `agentkernel.sandbox` imports cleanly; the `sandbox:` config section parses with
  defaults, env overrides, and the single-backend sugar; capability stays inert when disabled.
- **Files:** `sandbox/__init__.py`, `sandbox/model.py`, `sandbox/errors.py`;
  `core/config.py` (new `_Sandbox*` classes + root field); `ak-py/pyproject.toml` (the
  `sandbox-docker` extra). (Amended 2026-07-21 during PR #364 review: the `e2b`, `daytona`,
  and `kubernetes` extras were originally declared here too but are deferred to land with
  their providers in iterations 9–10, so an installable extra never precedes a usable
  provider.)
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

- **Goal:** agents get the sandbox system tools when enabled (the five execution/file/task tools
  here; the three session-lifecycle tools — list/new/destroy — were added within this surface
  during testing, for eight total); task-completion ingestion works;
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
  `sandbox/factory.py`, `examples/cli/sandbox/` (demo + README + config.yaml).
- **Steps:** spec §First-party providers (rows + notes for these two); wire both into
  `SandboxProviderFactory._build` as `if/elif` real-import branches (`require_extra("sandbox-docker", …)`
  for docker; no extra for stdlib `local_subprocess`) and remove their `_BUILTIN_PROVIDERS`/`_BUILTIN_EXTRAS`
  registry entries (spec §Factory, #541).
- **Verify:** `uv run pytest tests/test_sandbox_providers.py -k "subprocess or docker"`
  (real subprocess; mocked docker SDK); manual: `cd examples/cli/sandbox/basic && uv run demo.py`
  with the `local_subprocess` profile.

## Pre-merge: documentation + skills sync (brought forward)

Originally iteration 12; brought forward (2026-07-21) and **scoped to the implemented surface
(iterations 1–6)** so the first release merges with docs and skills already aligned. The
remaining surfaces (AWS broker plane, not-yet-landed providers) are deferred to their own
post-merge iterations.

- **Goal:** every documentation and skill surface matches what iterations 1–6 shipped.
- **Files/surfaces:**
  - `docs/docs/advanced/sandbox.md` (new page) + `docs/sidebars.js` row: capability overview,
    enable/disable, the full config reference (profiles, scopes, policy, identity,
    `principal_resolver`, broker, single-backend sugar, `agents` scoping,
    `tool_output_max_chars`), the eight system tools, session lifecycle + recreation notices,
    the shipped providers (`local_subprocess`, `docker`) and isolation-tier honesty,
    thread/embedded broker flavors, and BYO provider/resolver extension. Document only the
    landed surface; note AWS `sqs` broker + other providers as "coming in later iterations".
  - `docs/docs/examples/overview.md`: add the `cli/sandbox/{basic,profiles,policy}` and
    `api/sandbox-identity` examples.
  - `ak-py/README.md` (config/feature section) — sandbox capability + the four example dirs.
  - Root `README.md` / `DEVELOPER_GUIDE.md` — add sandbox to the capability list if enumerated.
  - New dev skill `.agents/skills/ak-dev-new-sandbox-provider/` (clone
    `ak-dev-new-guardrail-provider`: provider file → capabilities declaration → factory
    `if/elif` real-import branch + `_BUILTIN_PROVIDER_NAMES` → config block → extra → contract
    tests → example → docs checklist).
  - Skill inventory: `docs/docs/agent-skills.md` (+1 dev skill → count `fifteen`, table row).
    (There is no `docs/specs/agent-skills.md`; the only historical inventory,
    `docs/specs/246-agent-skills/design.md`, is a point-in-time design doc and is left as-is.)
  - `.agents/skills/ak-dev-architecture/SKILL.md`: add the sandbox capability to the directory
    structure and pluggable-capability lists; `ak-dev-testing-conventions` test-file table
    gains the three sandbox test files.
  - User skills under `ak-py/src/agentkernel/skills/`: update `ak-add-capabilities` (sandbox is
    a new config-driven capability) and `ak-test` only if their enumerations are affected;
    refresh evals if changed.
- **Steps:** run the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` flows
  over the iterations 1–6 delta.
- **Verify:** docs site builds (`cd docs && npm run build`); `make lint-check-all` clean; skill
  eval JSON parses; inventory counts match the `.agents/skills/` directory.

## Merge checkpoint

- **Goal:** land iterations 1–6 (plus the brought-forward docs/skills) on `develop`.
- **Steps:** `cd ak-py && uv run pytest` and `make lint-check-all` both green (the only known
  failures are the pre-existing `test_cli_tester.py` live-LLM tests, unrelated to this branch);
  confirm CODEOWNERS for the touched paths; open the PR against `develop` with the #494 summary;
  merge once approved.
- **After merge:** resume at iteration 7. Iterations 7–11 below are **post-merge**.

## Iteration 7 (post-merge): ec2_ssm provider — mode-3 attach checkpoint

- **Goal:** attach-to-existing-runtime working end-to-end against a real EC2 instance via SSM,
  driven from a local (thread-broker) deployment — the checkpoint for evaluating the attach
  model and the identity mapping before further iterations proceed.
- **Files:** `sandbox/providers/ec2_ssm.py`, `sandbox/factory.py`; `examples/cli/sandbox/` extended
  with an `ec2_ssm` profile (`attach_to` fed via `AK_SANDBOX__PROFILES__EC2__EC2_SSM__ATTACH_TO`).
- **Steps:** spec §First-party providers (`ec2_ssm` row + notes: `send_command` +
  `get_command_invocation` polling, `python3 - <<'EOF'` heredoc wrapping, attach-only `create`,
  no-op `destroy`), §PrincipalResolver mapping (agent: default boto3 chain; user:
  `sts:AssumeRole` + SSM `RunAs`); wire `ec2_ssm` into the factory `if/elif` (real import,
  `require_extra("aws", …)`) and append it to `_BUILTIN_PROVIDER_NAMES` (spec §Factory).
- **Verify:** `uv run pytest tests/test_sandbox_providers.py -k "ssm"` (mocked boto3: command
  call shapes, heredoc wrapping, AssumeRole/RunAs arguments per identity mode); manual: run the
  example against a real instance (agent runs `run_command`/`run_code` over SSM, reuses the
  same `sandbox_session_id` across turns). **Pause here for evaluation — iterations 8+ proceed
  only after this checkpoint is reviewed.**

## Iteration 8 (post-merge): AWS broker plane — sqs flavor, workers, terraform

- **Goal:** brokered execution on AWS: SQS client flavor, ECS + Lambda workers, DB-first
  completions via the reused `ResponseStore`, session inventory + idle sweep, payload offload,
  `worker_timeout_ceiling` fail-fast, completion events onto the agent input queue.
- **Files:** `deployment/aws/sandbox/{__init__,sqs_broker,ecs_worker,lambda_worker}.py`;
  `deployment/aws/__init__.py` (export `SandboxBrokerRunner`);
  `ak-deployment/ak-aws/common/sandbox_broker/` (module with `mode` variable + the four
  outputs).
- **Steps:** spec §Broker flavors (`sqs`), §Completion delivery, §Broker-side session
  inventory, §Fail-fast timeout ceiling, §Documentation/provisioning (terraform bullet);
  add the `sqs` entry to `_BUILTIN_BROKERS` in `sandbox/factory.py` (spec §Factory).
- **Verify:** `uv run pytest tests/test_sandbox_broker.py` (stubbed boto3: message schema,
  DB-before-event ordering, emission rule, `on_permanent_failure` → failed completion, offload,
  ceiling rejection); `terraform validate` in the module.

## Iteration 9 (post-merge): Cloud SaaS providers — e2b, daytona

- **Goal:** the two cloud sandbox backends, config-swappable.
- **Files:** `sandbox/providers/e2b.py`, `sandbox/providers/daytona.py`, `sandbox/factory.py`,
  `ak-py/pyproject.toml` (declare the `e2b` and `daytona` extras — deferred from iteration 1).
- **Steps:** spec §First-party providers (rows + notes); declare the `e2b`/`daytona` extras with
  version floors confirmed against current SDK releases (flagged in spec §Consumer changes); wire
  `e2b` (`require_extra("e2b", …)`) and `daytona` (`require_extra("daytona", …)`) into the factory
  `if/elif` as real imports and append them to `_BUILTIN_PROVIDER_NAMES` (spec §Factory).
- **Verify:** `uv run pytest tests/test_sandbox_providers.py -k "e2b or daytona"` (mocked
  SDKs: call shapes, native idle timeout pass-through, `to_thread` for daytona).

## Iteration 8.5 (post-merge): process-exit cleanup backstop (`atexit`)

Deferred from the pre-merge scope during PR #364 review (2026-07-21): spec §Idle timeout and
design.md require an `atexit`/signal backstop that closes/destroys sandboxes the process still
holds on exit (chiefly the `per_runtime` scope, and any leaked `per_session` handles), so a
container-backed provider doesn't leave orphaned containers. Not implemented in iterations 1–6.

- **Goal:** `SandboxManager` registers a process-exit hook that best-effort destroys tracked
  `per_runtime` sandboxes (and closes live handles), guarded so it is a no-op when the capability
  is disabled and safe under teardown ordering.
- **Files:** `sandbox/manager.py`.
- **Steps:** spec §Idle timeout (the `atexit` backstop clause); wire it when the first process-
  lifetime backend (`docker`) makes orphaning observable — hence sequenced with the AWS/cloud
  work rather than pre-merge, where only `local_subprocess` (temp dirs, OS-reclaimed) shipped.
- **Verify:** a `per_runtime` docker sandbox is destroyed on interpreter exit (mocked provider
  asserting `destroy` called via the registered hook).

## Iteration 10 (post-merge): Remaining attach-mode / AWS-native providers — kubernetes, bedrock_agentcore

- **Goal:** the remaining mode-3 backend and the AWS-native backend, with both identity modes
  where declared — informed by the iteration-7 checkpoint findings.
- **Files:** `sandbox/providers/kubernetes.py`, `sandbox/providers/bedrock_agentcore.py`,
  `sandbox/factory.py`, `ak-py/pyproject.toml` (declare the `kubernetes` extra — deferred from
  iteration 1; `bedrock_agentcore` rides the existing `aws` extra).
- **Steps:** spec §First-party providers (rows + notes), §PrincipalResolver mapping table
  (impersonation headers, `sts:AssumeRole`); wire `kubernetes` (`require_extra("kubernetes", …)`)
  and `bedrock_agentcore` (`require_extra("aws", …)`) into the factory `if/elif` as real imports
  and append them to `_BUILTIN_PROVIDER_NAMES` (spec §Factory; the interim registry maps were
  already deleted in iteration 6).
- **Verify:** `uv run pytest tests/test_sandbox_providers.py -k "kubernetes or bedrock"`
  (mocked SDKs; principal-mapping arguments asserted per mode).

## Iteration 11 (post-merge): Tests — coverage completion and lint

- **Goal:** the full spec §Testing matrix is present and green; no coverage gaps against the
  design's requirements checklist.
- **Files:** `tests/test_sandbox.py`, `tests/test_sandbox_broker.py`,
  `tests/test_sandbox_providers.py` (fill any assertions not landed with their iteration).
- **Steps:** walk spec §Testing item by item; no existing test file changes (verified in spec
  §Testing — the autouse hook-cache reset in `tests/test_runtime.py:15-23` already
  accommodates the third system pre-hook, and no patch targets move).
- **Verify:** `cd ak-py && uv run pytest` and `make lint-check-all` both clean.

## Iteration 12 (post-merge): Final docs and skills sync

Most of this iteration was **brought forward** to the pre-merge checkpoint above (2026-07-21)
and is done for the iterations 1–6 surface. What remains here is the documentation/skill work
for the surfaces that land *after* the first merge:

- **AWS broker plane** (iteration 8): `ak-deployment/ak-aws/` README for the new
  `sandbox_broker` module; the `docs/docs/advanced/sandbox.md` broker section grows from
  "thread/embedded only" to include the `sqs` flavor, workers, and queue-mode deployment.
- **Remaining providers** (iterations 7, 9, 10): each adds its row to the provider/isolation
  table on `docs/docs/advanced/sandbox.md`, its extra to `ak-py/README.md`, and (where it
  introduces new identity mapping) a note to the `ak-dev-new-sandbox-provider` skill.
- **Final pass:** re-run `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch`
  over the full post-merge delta so nothing drifted.
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
