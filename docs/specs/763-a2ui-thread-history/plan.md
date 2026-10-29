# #763: a labelled structured reply survives a thread reload — Implementation Plan

Five iterations, each leaving the branch green. The order is shape first, then the two writers, so no
intermediate state serves a wire form that later changes. Detail lives in [`spec.md`](spec.md);
this is the order only.

Branch: `feature/763-a2ui-threads`, off `feature/706-a2ui-transport-agnostic` (#706 adds
`AgentReplyAny.media_type`, which this depends on). Paths relative to `ak-py/`.

## Iteration 1: the message shape

- **Goal:** `ThreadMessage` can hold a labelled payload and knows its own wire form. Nothing writes
  one yet, so no behaviour changes.
- **Files:** `src/agentkernel/integration/thread/model.py`,
  `src/agentkernel/integration/thread/thread_chat.py`
- **Steps:**
  1. Add the imports, widen `content`, add `media_type`, add the pairing validator and `to_wire()`
     (spec.md § `ThreadMessage`).
  2. Point the read route's message dump at `to_wire()` (`thread_chat.py:380`).
  3. Add the model tests from spec.md § Testing → New, first bullet — including the
     `name: null` / `mime_type: null` guard that justifies the named exclusion.
- **Verify:** `uv run pytest tests/test_thread_integration.py tests/test_thread_router.py tests/test_thread_store.py tests/test_thread_manager.py`

## Iteration 2: the direct path writes the label

- **Goal:** a labelled reply recorded through `AgentThreadRequestHandler` stores the object and the
  label, and reads back that way.
- **Files:** `src/agentkernel/integration/thread/recorder.py`,
  `src/agentkernel/integration/thread/manager.py`, `tests/test_thread_integration.py`,
  `tests/test_cross_surface_parity.py`
- **Steps:**
  1. Replace `_as_thread_content` with `_as_thread_message`; add `media_type` to `post_run`
     (spec.md § `ThreadRecorder`).
  2. Add `media_type` to `ConversationThreadManager.append_message`, after `attachments`.
  3. **Update the tests this rename breaks, in this iteration**, or the branch is red:
     `test_thread_integration.py:288-337` (`TestThreadContentEncoding`), `:135` (the
     `append_message` call assertion), and `test_cross_surface_parity.py:139-147`.
- **Verify:** `uv run pytest tests/test_thread_integration.py tests/test_cross_surface_parity.py`

## Iteration 3: the queue path stops dropping the label

- **Goal:** both recording paths reach `ThreadMessage` with the same object and the same label.
- **Files:** `src/agentkernel/pipeline/agent_runner.py`
- **Steps:**
  1. Read `media_type` off the response body beside `result` in `process` (`agent_runner.py:55`).
  2. Thread it through `_record_thread_reply` to `post_run` (`agent_runner.py:117`), leaving its
     after-`_send_to_output` position, its never-raising contract and its lazy import alone.
- **Verify:** `uv run pytest tests/test_thread_pipeline_recording.py tests/test_pipeline_agent_runner.py`

## Iteration 4: tests

From spec.md § Testing. Everything not already pulled into iterations 1–3 by a rename:

- `tests/test_cross_surface_parity.py:150-160` — thread history joins
  `test_every_surface_agrees_on_the_payload`, the assertion the file exists for.
- `tests/test_thread_pipeline_recording.py:274-287` — rename the existing test to say it covers the
  *unlabelled* dict branch, and add the labelled sibling on `AgentRunner.process` (the consumer whose
  code changes shape most).
- `tests/test_thread_integration.py` — the end-to-end: a labelled and an unlabelled reply in one
  thread, read back through `GET /api/v1/threads/{session_id}`.
- `tests/test_thread_router.py` — the read route's message shape for both message kinds.
- **Verify:** `cd ak-py && uv run pytest` (full suite) and `make lint-check`

## Iteration 5: sync docs and skills

Surfaces this change invalidates, each verified against the branch:

- `docs/docs/advanced/a2ui.md:79` — the surface table row reads
  `| Conversation threads | the live reply; stored history is not labelled |`. It flips.
- `docs/docs/api/rest-api.md:157` — the `GET /api/v1/threads/{session_id}` paragraph gains the
  message shape, showing `content` as an object with `media_type` beside it.
- `docs/docs/advanced/threads.md`, near the store-backend selection (lines 86–91) — the breaking note
  for a bring-your-own `ThreadStore` that persists `content` into a typed text column.
- `.agents/skills/ak-dev-architecture/SKILL.md:398` — the `ThreadMessage` bullet in the Conversation
  Threads section.
- `.agents/skills/ak-dev-testing-conventions/SKILL.md:52,110,111` — the table rows for
  `test_cross_surface_parity.py`, `test_thread_integration.py` and
  `test_thread_pipeline_recording.py`.

Verified as needing **no** update:

- `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md` — its A2UI section's limits paragraph
  (lines 1494–1498) claims nothing about thread history; the two limits it names are unaffected.
- `examples/api/a2ui-openai/` — the demo mounts no thread handler.
- `docs/specs/706-a2ui-support/design.md:544-546` — a shipped spec recording what was true then;
  historical, not corrected.

Run the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` flows before merge to
confirm nothing else drifted.
