# #607: Human-in-the-loop in conversation thread history — Implementation Plan

The order [`spec.md`](spec.md) gets built in. Each iteration leaves `develop` green and the thread
read route's wire shape unchanged for every message that existed before it, so none of them needs a
later one to be correct.

| Iteration | Leaves you with |
|---|---|
| 1 | A message model that can hold a payload. Nothing writes one yet. |
| 2 | The direct REST surface recording pauses and decisions. |
| 3 | The direct SSE surface doing the same. |
| 4 | Both queue runners doing the same — all four sites done. |
| 5 | Parity proven across the four, and a runnable example. |
| 6 | Docs and skills synced. |

Expect merge conflicts with PR #817 in three files — `model.py`, `recorder.py`,
`pipeline/agent_runner.py` — concentrated in iterations 1, 2 and 4. See `design.md`'s closing note.

---

## Iteration 1: The message model

- **Goal:** `ThreadMessage` can carry a payload with a label, and the read route still returns
  exactly what it returned before.
- **Files:** `integration/thread/model.py`, `integration/thread/manager.py`,
  `integration/thread/thread_chat.py`, `tests/test_thread_integration.py`,
  `tests/test_thread_router.py`.
- **Steps:**
  1. Widen `content`, add `media_type`, the `_label_and_payload_agree` validator and `to_wire()`,
     and export `HITL_MEDIA_TYPE`, per *spec.md § the message model*.
  2. `append_message` takes `media_type` and the widened `content` (*§ append_message*).
  3. Switch `get_thread`'s message rendering to `to_wire()` (*§ the read route*). **This lands in
     this iteration, not later**: the moment `media_type` exists, `model_dump(mode="json")` emits
     `"media_type": null` on every message ever written.
  4. Tests: the validator's two halves, `to_wire()` with and without a label, and a pre-change
     message still round-tripping.
- **Verify:** `uv run pytest tests/test_thread_integration.py tests/test_thread_router.py` — and
  `uv run pytest` clean, since nothing else should move yet.

## Iteration 2: The recorder, and the direct REST surface

- **Goal:** a pause and a decision are recorded correctly through `AgentThreadRequestHandler`.
- **Files:** `integration/thread/recorder.py`, `tests/test_thread_integration.py`,
  `tests/test_cross_surface_parity.py`.
- **Steps:**
  1. Add `_as_user_message` and call it from `pre_run` (*spec.md § what is recorded*) — the decision
     dict built as one literal so `prompt` precedes `resume`.
  2. Rename `_as_thread_content` → `_as_thread_message`, return a `(content, label)` pair, add the
     `AgentPausedReplyAny` branch **first**, and give `post_run` its `media_type` parameter.
  3. Update the callers the rename breaks: `TestThreadContentEncoding`
     (`tests/test_thread_integration.py:288-337`, five cases) and
     `tests/test_cross_surface_parity.py:139-144`. Same expected encodings, now paired with `None`.
  4. Tests, extending `TestThreadPauseAndResume`: decision-only, decision-with-prompt as one
     message, the three statuses identical, a paused reply's stored content, and a rejected
     decision leaving its message with no assistant message.
- **Verify:** `uv run pytest tests/test_thread_integration.py tests/test_cross_surface_parity.py`.
  `_run_with_recording` itself is untouched — if these pass, the direct REST surface is done.

## Iteration 3: The direct SSE surface

- **Goal:** a streamed run that pauses records the pause instead of nothing.
- **Files:** `integration/thread/thread_chat.py`, `tests/test_thread_integration.py`.
- **Steps:**
  1. Add the `paused` local to `_stream_with_recording`'s generator and record it in preference to
     the accumulated deltas (*spec.md § Direct SSE*).
  2. Keep the `deltas`-only guard for the ordinary path.
  3. Tests: a stream ending in `RunPaused` records the pause; one that streams text *then* pauses
     records **only** the pause; an ordinary stream still records its text; a halted stream still
     records nothing.
- **Verify:** `uv run pytest tests/test_thread_integration.py`.

## Iteration 4: Both queue runners

- **Goal:** the queue and queue-streaming sites record the same message as the direct ones.
- **Files:** `pipeline/agent_runner.py`, `tests/test_thread_pipeline_recording.py`.
- **Steps:**
  1. `AgentRunner.process` builds the `AgentPausedReplyAny` from the `status: "PAUSED"` body keys
     and passes it as `result` (*spec.md § Queue*). `_record_thread_reply` is not touched.
  2. `StreamAgentRunner.process` builds it from the `run_paused` chunk event and records under
     `202` (*§ Queue streaming*).
  3. Tests, beside the existing cases (`:266-340`, `:343-375`): a `PAUSED` body records the pause; a
     streamed run ending in `run_paused` records it; an unmarked message still records nothing.
- **Verify:** `uv run pytest tests/test_thread_pipeline_recording.py`.

## Iteration 5: Parity and the example

- **Goal:** the four sites are proven to agree, and there is something runnable to look at.
- **Files:** `tests/test_cross_surface_parity.py`, `examples/api/thread-openai/app.py`,
  `examples/api/thread-openai/app_test.py`.
- **Steps:**
  1. Parity test: one paused reply recorded through the direct handler and both queue runners
     produces identical stored bytes.
  2. Example: bind one tool with `needs_approval=True` on `assistant_agent`.
  3. Example test: the DoD's happy path — ask → `202` `status: "PAUSED"` → resume → the read route
     shows question, decision and answer in order → one ordinary follow-up turn still works.
- **Verify:** `uv run pytest` in `ak-py`, and `cd examples/api/thread-openai && ./build.sh &&
  uv run pytest -s` with an `OPENAI_API_KEY`.

## Iteration 6: Sync docs and skills

Each surface is checked against the branch and either updated or explicitly confirmed as needing
nothing, then run through `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch`.

**Skills — must change:**

| File | Line | Why |
|---|---|---|
| `.agents/skills/ak-dev-architecture/SKILL.md` | 394 | `ThreadRecorder` — `pre_run` records a decision payload, `post_run` takes a label |
| `.agents/skills/ak-dev-architecture/SKILL.md` | 398 | `ThreadMessage` — `content` is text *or* a payload, `media_type` says which |
| `.agents/skills/ak-dev-architecture/SKILL.md` | 378 | `AgentThreadRequestHandler` — "skips recording on an error chunk or empty stream" is now wrong for a paused stream |
| `.agents/skills/ak-dev-architecture/SKILL.md` | 896 | `AgentRunner._record_thread_reply`'s lazy-import note — add that the runners reconstruct a paused reply |
| `.agents/skills/ak-dev-testing-conventions/SKILL.md` | 110, 111 | both thread test files gain pause/resume recording |
| `.agents/skills/ak-dev-testing-conventions/SKILL.md` | 52 | `test_cross_surface_parity.py` now also pins a paused reply |

**Docs — must change:**

| File | Why |
|---|---|
| `docs/docs/advanced/threads.md` | a section under *Reading Threads* (:151): the two message kinds, the `content`/`media_type` pair, the worked example |
| `docs/docs/advanced/human-in-the-loop.md` | one section after *Answering it* (:74): what a pause looks like in thread history |
| `docs/docs/api/rest-api.md` | :157 — the single-thread route's message shape |
| `examples/api/thread-openai/README.md` | the gated tool and the pause/resume exchange |

**Confirmed as needing no update** (verify, do not assume): `ak-dev-code-quality`,
`ak-dev-write-spec`, every `ak-dev-new-*` skill (no new backend, provider or adapter),
`docs/docs/api/agui-server.md` (AG-UI records no threads), the deployment and queue-mode docs (no
topology change), and `docs/docs/advanced/threads.md`'s *Storage Backends* section (:214) — the six
backends are untouched.

- **Verify:** both sync flows clean, `cd ak-py && uv run pytest` green, and `make lint-check-all`.
