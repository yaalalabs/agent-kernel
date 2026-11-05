# #836: Record AG-UI runs as conversation threads — Implementation Plan

Nine iterations on `feature/836-agui-thread-recording`, which is stacked on #827
(`feature/607-hitl-threads-support`). The shared pieces come first, then one path per iteration, so
each leaves the branch green. Section numbers refer to [spec.md](spec.md).

## Iteration 1: `StreamedReply`

- **Goal:** a streamed run can be reduced to the one thing a thread records.
- **Files:** `ak-py/src/agentkernel/integration/thread/recorder.py`, `ak-py/tests/test_thread_streamed_reply.py` (new).
- **Steps:**
  1. Add `StreamedReply` beside `ThreadRecorder` (spec §1), with the precedence error > pause > `DataMessage` > text > nothing.
  2. Build the paused reply field-for-field as #827's `_stream_with_recording` does.
  3. Write the unit tests listed under spec Testing → `test_thread_streamed_reply.py`.
- **Verify:** `uv run pytest tests/test_thread_streamed_reply.py tests/test_thread_integration.py`.

## Iteration 2: `AGUIThreadRecorder`

- **Goal:** an AG-UI run can be turned into `ThreadRecorder` calls; nothing calls it yet.
- **Files:** `ak-py/src/agentkernel/integration/agui/recorder.py` (new), `ak-py/tests/test_agui_recorder.py` (new).
- **Steps:**
  1. Add the class with `create`, `chat_request`, `pre_run`, `post_run` (spec §2).
  2. `chat_request`: explicit `prompt` (even `""`), `ResumeSpec` copied from the `AgentResumeRequestAny`.
  3. `pre_run`: `ValueError` → `HTTPException(400)`. `post_run`: no-op on `None`, log and swallow on failure.
  4. Write the unit tests listed under spec Testing → `test_agui_recorder.py`.
- **Verify:** `uv run pytest tests/test_agui_recorder.py`.

## Iteration 3: Direct path

- **Goal:** `AGUIRequestHandler` records both turns when a `thread` block is present, and is unchanged without one.
- **Files:** `ak-py/src/agentkernel/integration/agui/handler.py`, `ak-py/tests/test_agui_handler.py`.
- **Steps:**
  1. `__init__`: `self._recorder = AGUIThreadRecorder.create()`.
  2. `_run`: after the session check, build the request and `pre_run` via `asyncio.to_thread`; pass the request to `_events` (spec §3).
  3. `_events`: feed every chunk to a `StreamedReply`; after the error returns and before the state snapshot, `post_run` via `asyncio.to_thread`.
  4. Extend the handler tests (spec Testing → `test_agui_handler.py`), including the "no block → byte-identical stream" case.
- **Verify:** `uv run pytest tests/test_agui_handler.py tests/test_agui_resume.py`.

## Iteration 4: Queue path, edge

- **Goal:** `AGUIPipelineRequestHandler` records the user turn and marks the message; the runner ignores the mark until iteration 5.
- **Files:** `ak-py/src/agentkernel/integration/agui/queue_handler.py`, `ak-py/tests/test_agui_queue_handler.py`.
- **Steps:**
  1. In `_run`, when `_recorder` is set, replace the `offload` call with `pre_run` via `asyncio.to_thread` (spec §4).
  2. Add `ATTR_THREAD` to the enqueue attributes when `_recorder` is set.
  3. Extend the queue-handler tests (spec Testing → `test_agui_queue_handler.py`): attribute present only with a block, single offload, 400 with nothing enqueued.
- **Verify:** `uv run pytest tests/test_agui_queue_handler.py`.

## Iteration 5: Queue path, runner

- **Goal:** `AgentRunner._process_agui` records the reply for a marked message.
- **Files:** `ak-py/src/agentkernel/pipeline/agent_runner.py`, `ak-py/tests/test_thread_pipeline_recording.py`.
- **Steps:**
  1. Import `StreamedReply` lazily inside `_process_agui`, beside the existing AG-UI imports.
  2. Feed every chunk to it; after the terminal chunk is sent, call `_record_thread_reply` with `202` for a pause, else `200` (spec §5).
  3. Rewrite the "Thread recording is likewise absent" docstring line.
  4. Extend the pipeline recording tests (spec Testing → `test_thread_pipeline_recording.py`).
- **Verify:** `uv run pytest tests/test_thread_pipeline_recording.py tests/test_pipeline_agent_runner.py tests/test_agui_queue_handler.py`.

## Iteration 6: Example

- **Goal:** `examples/api/agui` records its runs and serves them back, in both topologies.
- **Files:** `examples/api/agui/config.yaml`, `config.broker.yaml`, `app.py`, `app_test.py`, `README.md`.
- **Steps:**
  1. Add the `thread` blocks: `in_memory` in `config.yaml`, `valkey` in `config.broker.yaml` (spec §7).
  2. Mount `ThreadRESTRequestHandler(authoriser=DemoAuthoriser())` beside `AGUIPipelineRequestHandler` in `runner()` (spec §6).
  3. Add `test_a_run_is_recorded_as_a_thread` to `app_test.py`.
  4. Add the "Conversation history" README section.
  4a. Frontend: the thread fetch module, the list hook, the `__load` action, `open(id)`, the conversations column and the `/api` proxy, with `threads.test.ts` (spec §7).
  5. Check mode B by hand with the README's "Checking mode B by hand" steps (`README.md:375`), then read the thread back.
- **Verify:** `cd examples/api/agui && ./build.sh local && .venv/bin/pytest -s app_test.py`; `cd frontend && npm test && npm run typecheck`; `make lint-check-all`.

## Iteration 7: Tests

- **Goal:** the cross-surface guarantee is pinned and nothing else regressed.
- **Files:** `ak-py/tests/test_thread_integration.py`.
- **Steps:**
  1. Add the round-trip test: an AG-UI run and a REST run of the same scripted agent read back through `GET /api/v1/threads/{session_id}` match apart from `message_id` and `timestamp`.
  2. Run the spec's test command, then the full suite and lint.
- **Verify:** `cd ak-py && uv run pytest`, then `make lint-check`.

## Iteration 8: Sync docs and skills

Developer skills:

- `.agents/skills/ak-dev-architecture/SKILL.md`
  - `:366-374` (Conversation Threads intro): "mounting a thread chat handler is what enables it" and "the `thread` config block only parameterizes" are no longer the whole story — add AG-UI as a recording surface enabled by the block alone.
  - `:446` onward (AG-UI Integration): a bullet on thread recording — `AGUIThreadRecorder`, both paths, the `ATTR_THREAD` mark, and that the read routes are app-mounted.
  - `:469-476` (`AGUIPipelineRequestHandler`): `pre_run` replaces `offload` when threads are on.
  - `:925` (pipeline → integration lazy imports): `_process_agui` now also imports `StreamedReply`.
- `.agents/skills/ak-dev-testing-conventions/SKILL.md`
  - Add rows for `test_thread_streamed_reply.py` and `test_agui_recorder.py`.
  - `:113` (`test_thread_integration.py`) and `:114` (`test_thread_pipeline_recording.py`): append the AG-UI cases.

Bundled user skill:

- `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md`
  - `:581-652` (AG-UI Server): one line that a `thread` block records AG-UI runs, and that `ThreadRESTRequestHandler` must be mounted beside it for reloads.
  - `:985` (Conversation Thread Support): AG-UI listed as a recording surface.

Docs:

- `docs/docs/integrations/agui.md:206-210` (Notes and limits): runs are recorded when a `thread` block is present; reloading needs `ThreadRESTRequestHandler` mounted beside the AG-UI handler, with the two-handler snippet from spec §6.
- `docs/docs/advanced/threads.md:55` (Enabling Thread Support): AG-UI records with the block alone, but serves no read routes — mount `ThreadRESTRequestHandler` for those.

No update needed, verified:

- `examples/api/hitl`: no `thread` block in its `config.yaml`, so it behaves as before (design non-goal). `examples/api/agui` is updated in iteration 6.
- No changelog file exists; the release note ("a `thread` block now also records AG-UI runs") goes in the PR description.

Confirm with the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` flows before merge.

## Iteration 9: PR review fixes

- **Goal:** the PR #905 review findings are fixed.
- **Files:** the three example `uv.lock` files (restored to `develop`); `integration/agui/recorder.py`; `test_agui_recorder.py`, `test_agui_handler.py`, `test_agui_queue_handler.py`; frontend `useThreads.ts`, `threads.ts`, `threads.test.ts`; spec docs, `agui.md`, the architecture skill.
- **Steps:**
  1. Restore the example locks that pointed at `ak-py/dist`.
  2. The ownership check in `AGUIThreadRecorder.pre_run` (spec §2 rule 6) with its tests.
  3. Frontend: fetch the list once the token settles; a 401/403 reads as a rejected token.
- **Verify:** the spec's test command, the full suite, `npm test && npm run typecheck`, `make lint-check-all`.

## Before merge

- `develop` is merged into this branch, so the `rebase --onto` route no longer applies: after #827 lands, merge `develop` again, then re-verify spec.md's **#827** citations and the line numbers above.
