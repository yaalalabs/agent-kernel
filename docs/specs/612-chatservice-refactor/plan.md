# #612 Implementation Plan: Decouple thread support from ChatService and route messaging integrations through it

Five code PRs land on `develop` in strict order, all within one release (design decision: the
recording-dormant window between iterations 1 and 5 never ships in a release). Every iteration leaves
the branch working and tested. Detail lives in [spec.md](spec.md); this plan only orders it.

Delivery note (post-merge): the iterations shipped as a single PR (#613) in one release, with the
iteration ordering below preserved as the commit sequence; it remains the logical structure of the
change.

## Iteration 1: ChatService execution core, thread linkage removed (PR 1, `refactor:`)

- **Goal:** ChatService exposes `execute` / `execute_sync` / `execute_stream` / `execute_stream_sync`,
  contains no `core.thread` import, and every existing wrapper caller behaves identically (minus
  thread recording).
- **Files:** `ak-py/src/agentkernel/core/chat_service.py`;
  delete `ak-py/tests/test_thread_chat_service.py`; add `ak-py/tests/test_chat_service_core.py`.
- **Steps:**
  1. Delete the thread methods, their call sites, and the import (spec: "ChatService execution core").
  2. Add the four core methods with the validation rules (prebuilt list, prompt-optional, eager
     stream validation).
  3. Rebuild the four `process_*` wrappers over the core (error mapping, SSE framing unchanged).
  4. Write `test_chat_service_core.py` per spec Testing / Iteration 1.
- **Verify:** `cd ak-py && uv run pytest` passes with `test_chat_service_streaming.py`,
  `test_api_http.py`, `test_akagentrunner_stream.py`, `test_ecs_akagentrunner_stream.py`,
  `test_ws_lambda_stream.py`, `test_ecs_websocket_routes.py`, `test_api_multipart_fields.py`
  untouched.

## Iteration 2: Slack pilot (PR 2, `refactor:`)

- **Goal:** Slack handler runs through `ChatService.execute`; the integration test pattern exists.
- **Files:** `ak-py/src/agentkernel/integration/slack/slack_chat.py`;
  add `ak-py/tests/test_slack_integration.py`.
- **Steps:** apply the common recipe plus the Slack row of the spec's per-handler table (identity
  mapping, `AgentRequestAny("body")` in the prebuilt list, `ValueError` to the no-agent message);
  write the pilot tests (request building, attachment-only, error paths, chunking).
- **Verify:** `uv run pytest tests/test_slack_integration.py` plus full suite.

## Iteration 3: Webhook fan-out (PR 3, `refactor:`)

- **Goal:** WhatsApp, Messenger, Instagram, Telegram, and Teams on the core, behavior parity.
- **Files:** the five `integration/<platform>/<platform>_chat.py` files;
  add `ak-py/tests/test_whatsapp_integration.py`.
- **Steps:** per-handler rows of the spec table: collapse `run`/`run_multi` branches
  (Messenger/Instagram), thread the Telegram sender id through `_process_agent_message`, delete the
  dead `result.raw` branches, keep every platform message and chunking limit.
- **Verify:** `uv run pytest tests/test_whatsapp_integration.py` plus full suite.

## Iteration 4: Gmail (PR 4, `refactor:`)

- **Goal:** Gmail's `_process_with_agent` runs one `execute` call; the riskiest consumer gets tests.
- **Files:** `ak-py/src/agentkernel/integration/gmail/gmail_chat.py`;
  add `ak-py/tests/test_gmail_integration.py`.
- **Steps:** Gmail row of the spec table (collapse both run branches, `str(reply)`, `ValueError`
  logs and returns None); handler-level tests for single-text, text+attachments, and no-agent paths.
- **Verify:** `uv run pytest tests/test_gmail_integration.py` plus full suite.

## Iteration 5: Thread integration package (PR 5, `refactor:`)

- **Goal:** thread support is a mountable integration; no thread code remains under `api/`.
- **Files:** add `ak-py/src/agentkernel/integration/thread/{__init__.py,recorder.py,thread_chat.py}`
  and `ak-py/src/agentkernel/thread.py`; relocate the whole `core/thread/` module (authoriser,
  manager, model, naming, store/) into `integration/thread/` with import-path fixes only; delete
  `ak-py/src/agentkernel/api/thread.py`; edit `ak-py/src/agentkernel/api/__init__.py` (drop the
  export) and `api/http.py` (drop the auto-mount block); edit `core/config.py` (thread field
  description and class docstring only); update
  `examples/api/thread-openai/{app.py,app_test.py,README.md,config.yaml if needed}` and
  `examples/api/multimodal/thread-openai/{app.py,app_test.py,README.md}`; add
  `ak-py/tests/test_thread_integration.py`; re-point the thread-related test suites
  (`test_thread_router.py`, `test_thread_manager.py`, `test_thread_store*.py`,
  `test_store_builders.py`, `test_thread_multimodal_hook.py` if needed) to the new import paths.
- **Steps:**
  1. `ThreadRecorder` (spec: "Thread integration package"), preserving message strings and the
     no-phantom-thread ordering.
  2. `AgentThreadRequestHandler` with the agent-availability precheck, non-stream and stream chat
     overrides, and composed read routes; move `ThreadRESTRequestHandler` verbatim.
  3. The removals (`api/thread.py`, export, auto-mount) and the config description change.
  4. Update both examples to mount `AgentThreadRequestHandler` from `agentkernel.thread`.
  5. Write `test_thread_integration.py` per spec Testing / Iteration 3, including the end-to-end
     read-back test.
- **Verify:** full suite; `cd examples/api/thread-openai && ./build.sh && uv run pytest -s` (and the
  multimodal twin) against the updated app.

## Iteration 6: Tests, regression sweep, release notes

- **Goal:** the whole change is green and its breaking changes are written down.
- **Steps:**
  1. `cd ak-py && uv run pytest` and `make lint-check-all` across the final state.
  2. Confirm the moved/changed patch targets match spec Testing (new suites patch
     `agentkernel.integration.<platform>.*` instance attributes and
     `agentkernel.integration.thread.*`; the `agentkernel.core.chat_service.*` targets are unchanged).
  3. Draft release notes covering spec Behavioural changes items 1-4 (recording relocation, `user_id`
     no longer enforced on non-thread paths, auto-mount removal, import-path move).
- **Verify:** clean pytest + lint on the assembled branch state.

## Iteration 7: Sync docs and skills

Run `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` before merge; the surfaces
below are the known-invalidated set to check off.

The layering diagram and call rubric (spec: "Documentation: chat execution layering diagram") are
the anchor deliverable of this iteration; they land in `execution-flow.md`, `overview.md`, and the
two skills named below, copied verbatim from the spec. The "ChatService vs AgentService" comparison
section (same spec section) lands in `overview.md` and the `ak-dev-architecture` skill.

Dev skills (`.agents/skills/`):

- `ak-dev-architecture/SKILL.md`: add the layering diagram and rubric to the ChatService section;
  update the ChatService description and thread sections
  (`ConversationThreadManager` "shared by ChatService and ThreadRESTRequestHandler" at `:199`,
  `ThreadRESTRequestHandler` located at `api/thread.py` at `:205`, directory map `:323`, execution
  flows referencing `ChatService.process_stream_chat_async` `:643`), plus the new
  `integration/thread/` package and the core methods.
- `ak-dev-new-messaging-integration/SKILL.md`: the AgentService pattern (`:25`, `:50`, `:115`)
  becomes the `ChatService.execute` recipe, with the rubric's "integration calls the core" rule
  stated.
- `ak-dev-testing-conventions/SKILL.md`: test-file table gains the four new suites and drops
  `test_thread_chat_service.py`.

Bundled user skills (`ak-py/src/agentkernel/skills/`):

- `ak-add-capabilities/SKILL.md` (`:719-743`) and `evals/evals.json`: thread enablement flow changes
  from "add the config block" to "mount AgentThreadRequestHandler"; read routes no longer appear
  automatically; `user_id` requirement scoped to the thread handler.
- `ak-add-integration/SKILL.md`: integration recipe moves to `ChatService.execute`.
- `ak-cloud-deploy/SKILL.md`: verify and state that thread recording no longer applies to deployment
  adapters (queue/WS/Lambda/Azure).

Docs site (`docs/docs/`):

- `advanced/threads.md`: major rewrite; auto-mount claim (`:116`), `user_id`-required-everywhere
  claims (`:34`, `:62`), mounting example (`:149-160`), sequence diagram (`:20`).
- `api/rest-api.md`: auto-mount and global `user_id` requirement (`:75`, `:88`).
- `advanced/queue-mode-guide.md`: add that thread recording does not apply in queue mode (current
  text only mentions consumer threads; verify no stale thread-support claim remains).
- `architecture/execution-flow.md`: replace the Request Lifecycle diagram's lumped
  "ChatService / AgentService" node with the spec's layered diagram and add the call rubric.
- `architecture/overview.md`: split the "AgentService / ChatService" node in the component diagram
  (`:26`) and the layer table row (`:113`) into the presentation/core/AgentService layering.
- Terminology sweep (spec: "Terminology sweep" under the layering-diagram section): rewrite the
  conflated mentions at `execution-flow.md:11`, `core-concepts/overview.md:180`, and
  `api/a2a-server.md:76` using the spec's canonical layer names; verify `execution-flow.md:61` and
  the solo-ChatService pages the spec lists, updating only where behavior moved.
- `docs/docs/integrations/*.md`: expected to need **no** update (platform setup and config are
  unchanged); verify per page during the sync.

Package README (`ak-py/README.md`, shown on PyPI):

- The Conversation Thread Support section and the config example's `thread:` comment move from
  config-presence enablement to the mounting model (mount `AgentThreadRequestHandler`; `user_id`
  scoped to the thread handler's routes; read routes served by the handler).

Also: the root `AGENTS.md`/`README.md` and deployment READMEs are expected to need no update
(no renamed public entry points besides the thread handler); verify during the sync run.

- **Verify:** both sync skills report no remaining drift; docs build passes.
