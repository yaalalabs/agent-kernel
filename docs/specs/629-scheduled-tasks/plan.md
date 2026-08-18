# #629: Scheduling capability for deferred and recurring chat execution: Implementation Plan

Ordered breakdown of `spec.md` into **six phases, one PR per phase**, each leaving `develop` in a working, testable state. Phases 1 and 2 are independently mergeable groundwork with no scheduling behavior; phases 3 to 6 build the capability on top. Tests ship inside the phase that introduces the behavior, never in a trailing PR. Before each phase merges, run the `ak-dev-sync-docs-from-branch` / `ak-dev-sync-skills-from-branch` flows for the surfaces that phase invalidates (listed per phase).

Phase 0 (already underway): this spec set (`design.md`, `spec.md`, `plan.md`, `research/`) ships as its own `docs:` PR before implementation starts.

Dependencies: Phase 3 needs 1 (pagination util) and 2 (body fallback, status honoring); Phase 4 needs 1 (`AuthorisedRESTRequestHandler`) and 3; Phase 5 needs 3; Phase 6 is Terraform-only and merges last.

---

## Phase 1: Shared authorization and pagination refactor (PR 1, `refactor:`)

Behavior-preserving. Spec sections: "Shared authorization refactor", the pagination bullet of "ScheduleManager".

### Iteration 1.1: Relocate Authoriser + adapter

- **Goal:** `agentkernel.auth` is the **single** import path for `Authoriser` (matching `AuthValidator`); `AuthValidatorAuthoriser` available. Breaking import change — call it out in the PR body.
- **Files:** `auth/authoriser.py` (new), `auth/__init__.py`, `integration/thread/authoriser.py` (**deleted**), `integration/thread/__init__.py` (re-export **dropped**), `integration/thread/thread_chat.py` (imports from `...auth.authoriser`).
- **Steps:** move the class verbatim; generalize the docstring; add the adapter; delete the old module; drop the thread package's re-export; migrate every consumer in this same PR — `examples/api/thread-openai/app.py`, `examples/api/multimodal/thread-openai/app.py`, `docs/docs/advanced/threads.md`, `skills/ak-add-capabilities/SKILL.md`, `tests/test_thread_router.py`. Leave `docs/versioned_docs/` (frozen release snapshot) alone.
- **Verify:** `from agentkernel.auth import Authoriser` works; `agentkernel.thread` and `agentkernel.integration.thread` no longer expose an `Authoriser` attribute; both thread examples still import cleanly.

### Iteration 1.2: Shared AuthorisedRESTRequestHandler

- **Goal:** bearer parsing + 401 mapping live once.
- **Files:** `api/handler.py` (new base class), `integration/thread/thread_chat.py` (`ThreadRESTRequestHandler` subclasses it, drops its own `_resolve_user`).
- **Steps:** move `_resolve_user` verbatim (the three 401 detail strings unchanged).
- **Verify:** `tests/test_thread_router.py` passes with its **assertions unchanged** (only its 1.1 import line differs).

### Iteration 1.3: Shared pagination helpers

- **Goal:** cursor/limit helpers reusable outside the thread package.
- **Files:** `core/util/pagination.py` (new), `integration/thread/manager.py` (delegates to it).
- **Steps:** extract `encode_cursor`/`decode_cursor`/`clamp_limit` verbatim from `manager.py:27-54`.
- **Verify:** `tests/test_thread_integration.py` + `tests/test_thread_router.py` pass unchanged.

### Iteration 1.4: Tests and sync

- **Files:** `tests/test_authoriser_shared.py` (new: adapter behavior, `agentkernel.auth` export identity, plus a guard that the thread package no longer exposes `Authoriser`).
- **Steps:** add tests; sync the surfaces the relocation invalidates — `.agents/skills/ak-dev-architecture/SKILL.md` (thread section's location note → `agentkernel.auth`), `skills/ak-add-capabilities/SKILL.md` and `docs/docs/advanced/threads.md` (import lines, done in 1.1), and `.agents/skills/ak-dev-testing-conventions/SKILL.md` (add every test file this phase introduces to the inventory table). Add the breaking import change to `release-notes.md`.
- **Verify:** `cd ak-py && uv run pytest` and `make lint-check`.

---

## Phase 2: Queue-path groundwork (PR 2, `feat:`)

No scheduling yet; ships spec Behavioural changes 4, 5, 6, 9 (call them out in the PR body). Spec sections: "Trigger consumption changes", the 202 part of "ChatService interception", "Acting-user propagation".

Before merge, sync `.agents/skills/ak-dev-testing-conventions/SKILL.md` (inventory rows for every test file this phase introduces) and add Behavioural changes 4, 5, 6, 9 to `release-notes.md`.

### Iteration 2.1: request_id body fallback (pipeline)

- **Files:** `pipeline/agent_runner.py`.
- **Steps:** replace `_require_request_id` with `_resolve_request_metadata(message, body)` (attribute precedence, body fallback, attribute injection for output forwarding) in `AgentRunner.process` and `StreamAgentRunner.process`.
- **Verify:** new `tests/test_pipeline_agent_runner_schedule.py`.

### Iteration 2.2: request_id body fallback + status forwarding (ECS, serverless)

- **Files:** `deployment/aws/containerized/akagentrunner.py`, `deployment/aws/containerized/akoutputconsumer.py`, `deployment/aws/serverless/akagentrunner.py`.
- **Steps:** `_get_record_attributes(raw, body=None)` fallback in all three runner classes; ECS runner stops discarding the status and sends a `status_code` custom attribute; output consumer stores `status_code` (default 200, permanent failure 500).
- **Verify:** new `tests/test_ecs_agent_runner_schedule.py`, `tests/test_ecs_output_consumer_status.py`; `tests/test_akagentrunner_stream.py` unchanged.

### Iteration 2.3: Status-honoring sync responses

- **Files:** `pipeline/request_handler.py`.
- **Steps:** move `RequestHandler._build_sync_response` logic into the `RestHandler` base, extended for 2xx-non-200 (`JSONResponse`); delete the override.
- **Verify:** status-honoring cases added beside the existing pipeline request-handler tests; existing suite unchanged.

### Iteration 2.4: Acting-user propagation

- **Files:** `core/runtime.py`, `core/__init__.py`, `core/service.py`, `core/chat_service.py`.
- **Steps:** add `ACTING_USER_CACHE_KEY` to `core/runtime.py` and re-export it from `core/__init__.py`; thread `acting_user_id` as an explicit optional parameter from all four `ChatService` execution-core entry points through `AgentHandler.run_*` and `AgentService.run_multi`/`stream_multi` into `Runtime.run`/`stream`, where it is set on the volatile cache *inside* `async with session:` — the same lock whose `finally` clears the cache, so set and clear cannot race across concurrent same-session runs.
- **Verify:** propagation + per-run clearing cases added to `tests/test_chat_service_core.py`.

---

## Phase 3: Scheduling core, local and single-process (PR 3, `feat:`)

After this PR, a laptop `RESTAPI.run()` with a `schedule:` block defers chats, fires them via the local provider, and records occurrences. Spec sections: "Wire models", "Task model", "Configuration", "ScheduleProvider" (base/factory/local), "ScheduleStore" (base/builder/in_memory), "ScheduleManager", "Trigger bodies", "ChatService interception".

### Iteration 3.1: Config and wire models

- **Files:** `core/config.py` (`_Schedule*` classes + `AKConfig.schedule`), `core/model.py` (`ScheduleSpec`, `BaseChatRequest.schedule`, `BaseRunRequest.scheduled_task_id`/`scheduled_time`), `core/chat_service.py` (`known_fields`), `ak-py/pyproject.toml` (`schedule` extra: `croniter>=3.0`).
- **Verify:** `tests/test_schedule_model.py` (new), config-load case in `tests/test_config.py`.

### Iteration 3.2: Package skeleton: store + provider (local)

- **Files:** `schedule/__init__.py`, `model.py`, `errors.py`, `store/base.py`, `store/in_memory.py`, `provider/base.py`, `provider/local.py`.
- **Steps:** ABCs + factory/builder (in_memory and local branches only; redis/valkey/dynamodb short names raise the not-yet message pattern is NOT used here: they simply arrive in Phase 5, so the builder lists only shipped built-ins plus dotted-path BYO); local provider heap thread + token substitution + empty-attribute sends.
- **Verify:** `tests/test_schedule_provider_local.py`, in_memory part of `tests/test_schedule_store.py`.

### Iteration 3.3: ScheduleManager

- **Files:** `schedule/manager.py`.
- **Steps:** singleton, semantic validation, transport-compatibility fail-fast, create/amend/cancel with rollback, ownership, `record_trigger`, cursor pagination via `core/util/pagination.py`.
- **Verify:** `tests/test_schedule_manager.py`.

### Iteration 3.4: ChatService interception and thread handler

- **Files:** `core/chat_service.py` (`_maybe_schedule`, `_record_trigger`, 202 in the two process wrappers, `ResponseBuilder` 2xx `JSONResponse`, streaming terminal chunk), `integration/thread/thread_chat.py` (schedule check before `ThreadRecorder.pre_run` in both paths).
- **Verify:** `tests/test_chat_service_schedule.py` (all four entry points, 202 shapes, terminal chunk, unconfigured 400, no `AgentRequestAny` leak, recording log-and-continue); "schedule skips recording" case in `tests/test_thread_integration.py`; `tests/test_chat_service_core.py` unchanged.

### Iteration 3.5: End-to-end verify and sync

- **Steps:** manual e2e: `schedule:` block + `RESTAPI.run()`, one-time `at` a minute ahead, observe 202 then the fired run; full suite + lint; sync flows for this phase's surfaces (see Phase 6 list).
- **Verify:** `cd ak-py && uv run pytest`, `make lint-check`.

---

## Phase 4: Management API, agent tools, example (PR 4, `feat:`)

Spec sections: "Management REST handler", "Agent system tools", "Example".

### Iteration 4.1: ScheduleRESTRequestHandler + pipeline mounting

- **Files:** `schedule/handler.py` (new), `pipeline/io_handler.py` (generic `authoriser` param, conditional handler composition, eager `ScheduleManager.get()` at startup).
- **Verify:** `tests/test_schedule_router.py` (404/401/403/PUT/DELETE matrix); IOHandler startup fail-fast case.

### Iteration 4.2: System tools

- **Files:** `schedule/tools.py` (new), `core/tool.py` (the gated `SystemToolFactory.get_all` block).
- **Verify:** `tests/test_schedule_tools.py` (registration, `agents` scoping, acting-user, per-tool JSON contracts); `tests/test_sandbox.py` unchanged.

### Iteration 4.3: Example

- **Files:** `examples/api/schedule-openai/` (`app.py`, `config.yaml`, `README.md`, `build.sh`, `pyproject.toml`), following `examples/api/thread-openai/`.
- **Verify:** example runs locally; README curl transcript matches actual responses.

---

## Phase 5: Distributed stores and EventBridge provider (PR 5, `feat:`)

Spec sections: "ScheduleStore" backends, "ScheduleProvider" EventBridge.

### Iteration 5.1: redis/valkey/dynamodb stores

- **Files:** `schedule/store/redis_like.py`, `redis.py`, `valkey.py`, `dynamodb.py`; builder branches with `require_extra`.
- **Verify:** full `tests/test_schedule_store.py` (fake redis-like client, mocked `DynamoDBDriver`); `ScheduleStoreBuilder` unknown-type + BYO cases in `tests/test_store_builders.py`.

### Iteration 5.2: EventBridge provider

- **Files:** `schedule/provider/eventbridge.py`; factory branch with `require_extra("aws", ...)`.
- **Steps:** expression translation (5-to-6-field, `?` rule, `at()`), token-to-context-attribute mapping, `ActionAfterCompletion`, `State`, `SqsParameters`, error mapping, delete idempotency, `supported_transports = {"sqs"}`.
- **Verify:** `tests/test_schedule_provider_eventbridge.py` (mocked boto3, exact kwargs); transport-compatibility case already in `tests/test_schedule_manager.py` now exercises the real class attribute.

---

## Phase 6: Terraform and docs/skills sync (PR 6, `feat:` for the Terraform, sync riding along)

Spec section: "Terraform changes".

### Iteration 6.1: Containerized stack

- **Files:** `ak-deployment/ak-aws/containerized/`: `variables.tf`, `eventbridge.tf` (new), `dynamodb.tf`, `state.tf`, `iam.tf`, `outputs.tf`, `modules/queues/` (dedup variable), `modules/agent-runner/main.tf` (+`variables.tf`), `modules/rest-service/main.tf` (+`variables.tf`), `rest_service.tf`, `queue_mode.tf`.
- **Steps:** flags + check block, schedule group + execution role, input-queue dedup flip, schedule table, IAM pairs for both roles, guarded env injection, outputs.
- **Verify:** `terraform fmt -check` and `terraform validate` in the root module; a plan against a sandbox account shows only the flag-gated resources.

### Iteration 6.2: Serverless stack

- **Files:** `ak-deployment/ak-aws/serverless/`: `variables.tf`, `state.tf`, `outputs.tf`, `modules/queues/main.tf`, `modules/request-handler/main.tf`, `modules/agent-runner/main.tf`.
- **Verify:** same fmt/validate.

### Iteration 6.3: Docs and skills sync (final)

- **Surfaces the change invalidates** (confirm each with `ak-dev-sync-docs-from-branch` / `ak-dev-sync-skills-from-branch` before merge; the post-merge automation keeps them aligned afterwards):
  - `.agents/skills/ak-dev-architecture/SKILL.md`: new Scheduling section (abstractions, config block, interception point, trigger contract), directory-structure tree, `AKConfig` key-sections list, thread section's `Authoriser` location.
  - `.agents/skills/ak-dev-testing-conventions/SKILL.md`: test-file table rows for the new `tests/test_schedule_*` files.
  - `docs/docs/`: a new scheduling guide (mirroring `docs/docs/advanced/threads.md`, including the Terraform env-var table like `threads.md:247`), plus queue-mode guide notes for the trigger contract and 202.
  - `ak-deployment/ak-aws/containerized/modules/README.md` env-var tables (`:145-154`, `:231-240`) and both root Terraform READMEs' inputs tables.
  - Root `README.md` / `ak-py` README capability lists, `examples/` index if one names the API examples.
- **Verify:** sync flows report no remaining stale surface; full `uv run pytest` + `make lint-check-all` green.
