# #523: AG-UI protocol support — Implementation Plan

Build order for [spec.md](spec.md). **Seven PRs** and one non-PR closing step, two independent roots;
§-references point at `spec.md` sections rather than restating them.


| Iteration | PR                                                | Depends on          |
| --------- | ------------------------------------------------- | ------------------- |
| 1         | PR 1 — the streaming contract                     | —                   |
| 2         | PR 2 — attachment source forms                    | —                   |
| 3         | PR 3 — the AG-UI integration                      | 1, 2                |
| 4         | PR 4 — OpenAI + LangGraph                         | 1                   |
| 5         | PR 5 — Google ADK                                 | 1                   |
| 6         | PR 6 — Pydantic AI, and the end of the transition | 1, and 4 + 5 merged |
| 7         | PR 7 — docs and skills                            | 1-6, all merged     |


Iterations 1 and 2 can run in parallel. So can 4, 5 and 6's adapter work; only iteration 6's *last
step* waits on 4 and 5. Iteration 7 waits on all six.

**There is no separate tests iteration, but documentation is one**, and the split is deliberate:

- **Tests** ship with the behaviour they cover, because `ak-dev-write-spec`'s template requires every
  iteration to leave the branch working and testable. A trailing test iteration would mean six of the
  seven PRs merge untested.
- **Docs and skills are a trailing PR**, because **these seven PRs merge as one stack** — nothing
  reaches `develop` until all of them do. The rule a merged PR must never leave the docs describing
  behaviour it just changed therefore binds the *stack*, not each PR, and a trailing docs PR satisfies
  it while being the only arrangement where the docs are written against code that will not change
  again. Distributing them per-PR was tried first and fails four ways, each verified rather than
  predicted:
  1. **Docs describing the transition are born stale.** PR 6 deletes the transitional `str` branch
    before anything lands, so `develop` never contains it. A `TRANSITIONAL` note written into a skill
     at PR 1 documents code that never exists on the default branch — and the
     `ak-dev-testing-conventions` snippet is worse than stale: "yielding bare token strings still
     works" is false after PR 6, so an agent following it writes a broken test double.
  2. **The fidelity matrix cannot be written where it was owned.** `design.md:687` requires it to
    state per adapter which events each can fill, but PRs 4, 5 and 6 are what make them fillable.
     Assigning it to PR 3 gives one PR a document whose content is decided by the three after it.
     This one is structural, not an oversight in the inventory.
  3. **The inventory missed surfaces**, because it was derived by grepping for `StreamChunk` /
    `Runner.stream` / `delta` rather than by tracing what the change breaks:
     `core-concepts/runtime.md:55` and `architecture/overview.md:247` both describe the exact loop §4
     rewrites. Neither appears in the table below as originally written.
  4. **Per-PR ownership hid a test-scope gap of the same kind** — see iteration 6, step 5.

  **PR 7 is not optional.** Its safety comes entirely from being inside the stack: merging PRs 1-6
  without it ships docs describing the old contract, which is worse than the state before this work
  began. It is a hard condition on the merge, not a follow-up.

  The cost is that a reviewer of PRs 1-6 cannot check code against docs in the same PR. They check
  code against `spec.md` instead, which is what `ak-dev-review-pr` does regardless, since the spec is
  the contract.

---



## Iteration 1: The streaming contract (PR 1)

- **Goal:** the event model exists, `Runner.stream` is typed for it, and `StreamChunk` carries `event`.
The adapters still yield `str`; the only externally visible change is the synthetic
`message_start`/`message_end` frames on the streaming wire, recorded under Verify below.
- **Files:** `core/event.py` (new), `core/model.py`, `core/base.py`, `core/runtime.py`, `core/__init__.py`,
`framework/crewai/crewai.py`, `framework/smolagents/smolagents.py`,
`tests/test_stream_events.py` (new), `tests/test_runtime_stream_events.py` (new),
`examples/api/pydanticai-streaming/app_test.py`
- **Steps:**
  1. Add `core/event.py` — the twelve event classes and the `StreamEvent` discriminated union (§1), and
    export `StreamEvent` plus every member class from `core/__init__.py`. They are public API from PR 6
     on, so the export ships with the classes rather than being owned by a later PR.
  2. Add `event: StreamEvent | None` to `StreamChunk`, after `delta` (§2). `delta` stays a plain
    settable field — **not** a computed field; §2 explains which existing test decides this.
  3. Add the `supports_streaming` **property** to `Runner` (default `True`) and widen `stream`'s
    return annotation (§3). Declare `False` on `CrewAIRunner` and `SmolagentsRunner`; leave their
     bodies raising.
  4. Rewrite the `Runtime.stream` loop (§4): text extraction, hook chain, write-back into the event,
    `None` drops the whole chunk, `ReasoningDelta` through the hooks but out of `delta`, and the
     transitional `str` branch — which **normalizes into a `TextDelta` and falls through the same
     hook chain**, wrapped in one synthetic `MessageStart`/`MessageEnd` pair, carrying the comment
     that names PR 6. A branch that yields the string and skips the hooks silently disables every
     `on_stream_chunk` hook until PR 6; §4 rule 4 explains why no existing test would catch it.
  5. Write the two new test files. `test_runtime_stream_events.py` must assert hooks apply to the
    transitional `str` path and that reasoning never reaches `delta` — those two are the regression
     guards for step 4, and nothing in the current suite references `on_stream_chunk`.
- **Verify:** `cd ak-py && uv run pytest` — green with **exactly two edits to existing tests**, and
they are `tests/test_pipeline_request_handler.py`'s SSE wire-shape assertions and
`examples/api/pydanticai-streaming/app_test.py`'s frame accumulation. Any *other* edit means the
projection in §4 is wrong.
  - **`uv run pytest` in `ak-py` is not sufficient on its own.** It does not run example tests, so a
    green `ak-py` suite is not evidence that the examples are green. The second edit was found by the
     nightly `api` matrix entry `examples/api/pydanticai-streaming`
     (`.github/test-config.yaml:104`), not locally. Also run
     `grep -rn '\["delta"\]' examples --include="*.py"` before opening the PR.
  - **The original "zero edits" gate does not hold, and the reason matters.** The transitional branch
    adds two frames to every stream — a `message_start` at the head and a `message_end` at the tail,
     both carrying no `delta` — and `TestStreamSSE::test_stream_yields_sse_chunks` asserts
     `frames[0]` is the first text frame. §4's own design requires those frames, so the test's
     expectation is what is stale, not the implementation.
  - **The example failure is the same cause with a harder edge.** `app_test.py:79` did
    `"".join(f["delta"] for f in frames[:-1])` — unguarded — so it raises `KeyError: 'delta'` on the
     leading `message_start` frame rather than degrading quietly. It is fixed by filtering on the
     key's presence (`for f in frames if "delta" in f`), which is correct in both the transitional
     and the end state. The rewrite also adds assertions that `delta` and `event["content"]` agree
     and that boundary frames exist — the only end-to-end check anywhere that §4's projection holds
     through a real adapter and a real HTTP surface.
  - **Why §4 missed it:** the three files it names as the compatibility claim (§ *Existing test files
    that must NOT change*) all inject `StreamChunk`s into a fake service and never reach
     `Runtime.stream`, so none of them could have caught this. `test_pipeline_request_handler.py` is
     the only test in the suite that drives a real runner through the loop and asserts wire frames.
  - **PR 1 therefore does change the REST SSE wire.** Production consumers are unaffected — every
    `delta` reader either guards on it (`integration/thread/thread_chat.py:158`) or forwards chunks
     whole through `exclude_none=True` — but the changelog note must not claim a `delta`-reading
     frontend needs *no* change: one that appends `frame.delta` unguarded now appends `undefined`
     twice per response.



## Iteration 2: Attachment source forms (PR 2)

- **Goal:** all five attachment source forms work with `multimodal.enabled: true`, not just bare
base64. No AG-UI code involved.
- **Files:** `core/multimodal/hooks.py`, `tests/test_multimodal_source_forms.py` (new)
- **Steps:**
  1. Extend `_extract_attachment` to classify the source and return `consumable` (§8a). Split
    `data:` URIs into base64 plus their real mime type, dropping the `"image/jpeg"` fallback.
  2. Have `_process_attachments` return the set of consumed requests, and change the filter loop to
    retain the ones it declined (§8b). **This is the half that is easy to miss** — without it a URL
     attachment is deleted instead of merely undescribed.
  3. Write the new test file, covering all five forms.
  4. **Post-review additions.** Three things came out of PR #648's review:
     - **A `data:` URI with an empty payload is now dropped, not retained.** `_resolve_source` returns
       `Optional[...]`, so `data:image/png;base64,` resolves to `None` and takes the existing
       "no bytes" path — the same one `image_data=""` already took. Previously `not payload` was
       OR-ed with the base64-marker check, so a payloadless URI was classified non-consumable and
       forwarded to the adapter. Splitting that condition also separates two unrelated cases: an empty
       payload (no bytes, drop) and a non-base64 `data:` URI (real content, retain). Both halves are
       now tested, and the empty-payload test was confirmed to fail before the fix.
     - **§8a rewritten to the implemented shape.** It sketched a flat 5-tuple; the code uses a frozen
       `_ExtractedAttachment` dataclass plus a `_resolve_source` helper, which is the better shape and
       is now what the spec says. The two undocumented behaviours the reviewer flagged — non-base64
       `data:` URIs retained, and case-insensitive scheme/header matching — are recorded there too.
     - **The thread-off qualifier in design.md**, which the "all five forms work" claim was missing.
       See design.md; the thread path is a separate follow-up, and PR 7's `advanced/multimodal.md`
       must say which path each source form works on.
- **Verify:** `uv run pytest tests/test_multimodal_source_forms.py`, then the full suite. Existing
multimodal tests must pass unchanged — they exercise bare base64, which is untouched.



## Iteration 3: The AG-UI integration (PR 3)

The largest iteration, and the only one that needs AG-UI knowledge to review. Ordered so the branch
is testable at each step.

- **Goal:** a compliant AG-UI client can discover agents, start a run, receive the event stream, and
round-trip state.
- **Files:** `core/base.py`, `core/agui_state.py` (new), `core/tool.py`, `core/config.py`,
`ak-py/pyproject.toml`, `integration/agui/` (new, 4 modules), `examples/api/agui/` (new),
plus four new test files
- **Steps:**
  1. **Session key first** — `Session.Keys.AGUI_STATE` and its three accessors (§5). Independently
    testable, and everything else leans on it.
  2. `core/agui_state.py` — the four tool functions (`get_agui_state`, `update_agui_state`,
    `get_forwarded_props`, `get_agui_context`), their two `SystemTool` builders, and the two
     volatile-cache key constants this module owns (§5, §6). Docstrings are the LLM-facing tool
     schema; write them as such.
  3. Config: `_AGUIConfig` with the nested `state` and `client_context` blocks (§Config changes),
    then the two `SystemToolFactory` branches (§7). Both flags default `False`.
  4. `integration/agui/run_input.py` (§9) — there is **no** `authoriser.py`: AG-UI uses the shared
    `auth/authoriser.py` and `AuthorisedRESTRequestHandler` that PR #632 added to `develop`. The
     mapping is pure and testable without a server; cover every `InputContent` type for both `data`
     and `url` sources, and the history pre-filter — unknown roles and unknown content types in
     history are ignored, the same unknown content type in the final user message is a 400.
  5. `integration/agui/mapping.py` — `to_agui` plus its exhaustiveness test. Write the test with the
    mapping, not after.
  6. `integration/agui/handler.py` — routes, identity, run lifecycle, `StateSnapshot` (§9).
  7. `agui` extra in `pyproject.toml`, pinned `ag-ui-protocol>=0.1.16` — the floor is confirmed, not
    pending: the multimodal `InputContent` types first appear in 0.1.16 (§ the `agui` extra).
  8. `examples/api/agui/` — one static HTML file, no build step. It must show a tool call live *and*
    a state round-trip, and ship the config that enables both tool groups.
- **Verify:** `uv run pytest tests/test_agui_*.py`, then the full suite. Manually: run the example,
attach a file, confirm streamed text renders and a `StateSnapshot` arrives. **Tool calls cannot
render yet** — no adapter emits `ToolCallStart` until PR 4, so text arrives here via the
transitional normalization in §4 and the tool-call half of the example is exercised at PR 4.



## Iteration 4: OpenAI and LangGraph (PR 4)

- **Goal:** both adapters emit events with boundaries; they are reachable over AG-UI with full
fidelity.
- **Files:** `framework/openai/openai.py`, `framework/langgraph/langgraph.py`,
`tests/test_openai_runner.py`, `tests/test_langgraph_runner.py`
- **Steps:**
  1. OpenAI: stop filtering to `ResponseTextDeltaEvent`; map `RunItemStreamEvent` and the item
    boundaries (§10). Take correlation ids off the stream items — **do not** generate and store them
     (§10's adapter-state rule).
  2. LangGraph: add the `on_chat_model_start` / `on_chat_model_end` / `on_tool_start` / `on_tool_end`
    branches. Ids come from `on_chat_model_start`'s run id.
  3. Update both test files: `assert deltas == ["hi"]` becomes an assertion on the event sequence.
    `framework_context` round-trip assertions stay as they are.
- **Verify:** `uv run pytest tests/test_openai_runner.py tests/test_langgraph_runner.py`, then the
full suite.



## Iteration 5: Google ADK (PR 5)

- **Goal:** ADK emits events, including boundaries it has to derive.
- **Files:** `framework/adk/adk.py`, `tests/test_adk_runner.py`
- **Steps:**
  1. Stop `continue`-ing on non-partial events — that branch is where function calls and responses
    arrive.
  2. Derive the boundaries: `message_id` as a **local inside** `stream`, set on the first
    `partial=True` and cleared on the first `partial=False`. §10 explains why a `self.` attribute
     would be a cross-session bug rather than a crash.
  3. Map function calls and responses onto the tool-call events.
  4. Update `tests/test_adk_runner.py`, including a test that two concurrent `stream()` calls on the
    same runner instance do not share a `message_id`.
- **Verify:** `uv run pytest tests/test_adk_runner.py`, then the full suite.



## Iteration 6: Pydantic AI, and the end of the transition (PR 6)

- **Goal:** the last adapter emits events, and the scaffolding from iteration 1 is gone.
- **Files:** `framework/pydanticai/pydanticai.py`, `core/runtime.py`,
`tests/test_pydanticai_runner.py`, `tests/test_runtime_stream_events.py`, `tests/test_runtime.py`,
`tests/test_chat_service_core.py`, `tests/test_pipeline_request_handler.py`
- **Steps:**
  1. Replace `run_stream(...)` + `stream_text(delta=True)` with `run_stream_events()`.
  2. Re-plumb the two things that live inside the old `async with` block — session-message
    bookkeeping and `_store_framework_context` — so both still run only after the stream drains
     normally, inside the `try`, never in `finally` (§10).
  3. Update `tests/test_pydanticai_runner.py`, keeping the `framework_context` round-trip assertions
    intact — that is the regression this rewrite most easily causes.
  4. **Only once iterations 4 and 5 have merged:** delete the transitional `str` branch from
    `Runtime.stream`, and add a test asserting a `str`-yielding runner now fails loudly — the
     assertion is the pydantic `ValidationError` from `StreamChunk.event` rejecting a bare `str`
     (§4 rule 6), not merely an absence of output. **Narrow `Runner.stream`'s annotation from
     `AsyncGenerator[StreamEvent | str, None]` back to `AsyncGenerator[StreamEvent, None]`** in the
     same step (§3) — the union is transitional scaffolding and becomes permanent by omission if this
     is missed. The trailing bare `yield` in the base body **stays**: it is what makes the method an
     async generator rather than a coroutine, and is unrelated to the transition.
  5. **Migrate the three test doubles the deletion breaks**, none of which appear in §*Existing test
    files that change*: `tests/test_runtime.py:756-759` (the `Agent.current()`-during-stream double),
     `tests/test_chat_service_core.py:257-259` (acting-user propagation) and
     `tests/test_pipeline_request_handler.py:33-35` (the SSE wire-shape double). Each yields bare
     strings through `Runtime.stream`, so each raises `ValidationError` the moment the branch is
     gone — the same loud failure step 4 asserts for, arriving in three places that are not testing
     for it. Convert them to yield `MessageStart` / `TextDelta` / `MessageEnd`; the SSE test's frame
     assertions then hold unchanged, because the boundaries move from `Runtime.stream` to the double
     without changing the wire.
     - This gap has the same cause as the docs gaps in the header: §*Existing test files that change*
       lists the four files that assert on `Runner.stream` output directly, which is the set found by
        asking what reads the changed contract — not the set found by asking what the deletion breaks.
- **Verify:** `uv run pytest` — full suite. Grep `core/runtime.py` for the transitional comment and
confirm it is gone.

> If review returns PR 6 before 4 and 5, merge its adapter half and move step 4 to whichever PR lands
> last. The gate travels with the step, not the number. Note the stack makes this mostly moot: PR 6
> *is* last, so there is no later PR for the step to travel to.



## Iteration 7: Documentation and skills (PR 7)

- **Goal:** every docs and skills surface describes the merged end state — the streaming contract as
it finally is, with no reference to the transitional `str` branch, and the fidelity matrix filled in
from six adapters that now exist.
- **Depends on:** PRs 1-6, all merged into the stack. This is what makes the iteration writable at
all; see the header for why it cannot be distributed backwards.
- **Files:** the inventory below.
- **Steps:**
  1. **The streaming contract** — `core-concepts/runner.md`, `core-concepts/runtime.md`,
    `integrations/hooks.md`, `architecture/execution-flow.md`, `architecture/overview.md`, and the
     three dev skills. Describe the **end state only**: `Runner.stream` yields events,
     `supports_streaming` exists, `on_stream_chunk` sees text and its edit is written back,
     `ReasoningDelta` is kept out of `delta`. **Write nothing about the transition** — it does not
     exist on `develop`, and end-state guidance is correct in every state a reader can be in whereas
     transitional guidance is correct in only one.
  2. **The SSE wire shape**, stated once for the final behaviour: every frame carries `event`
    alongside `delta`; frames carrying a non-text event have no `delta` at all; an assistant message
     is bracketed by `message_start` / `message_end` frames. The mode table and the WebSocket
     `STREAM_CHUNK` payload carry the same shape.
  3. **The tool-call redaction limit** (§4 deferred note) in `integrations/hooks.md` — that no hook
    can see `ToolCallArgs` or `ToolCallResult`, and that `on_run` does not run on a streamed path
     either, so on a streamed run `on_stream_chunk` is the entire output-side defence and tool-call
     payloads have none.
  4. **Attachment source forms** — `advanced/multimodal.md`: all five now work; say which are
    described and stored and which pass through untouched.
  5. **AG-UI** — the new page under `advanced/`, plus its `docs/sidebars.js` entry and the
    `integrations/overview.md` row. This is where the **per-adapter fidelity matrix** lands, written
     against all six adapters as merged, stating plainly that CrewAI and smolagents are not reachable
     over AG-UI and why (`design.md:687-691`). Also the `thread_id`→`session_id` note, the ignored
     `tools` non-goal, `forwardedProps` being read-only and pull-based, and AG-UI state's session
     lifetime.
  6. **Example READMEs — five of them, and this surface was absent from the inventory entirely.**
    Every one shows a literal SSE or `STREAM_CHUNK` payload that is now incomplete. They are owned
     here rather than by PRs 1-3 for the usual reason plus a sharper one:
     `examples/api/pydanticai-streaming/README.md` is invalidated **twice** — its frame samples by
     PR 1, and lines 5-7, which name `run_stream()` / `stream_text(delta=True)` as what drives the
     stream, by PR 6's replacement of both with `run_stream_events()`. It cannot be written correctly
     until PR 6 exists.
  7. **Three pre-existing inaccuracies, fixed while in the neighbourhood.** All three show a terminal
    frame that carries a `delta`, which has never been true of any version of this code:
     `docs/docs/api/rest-api.md:353`, `docs/docs/deployment/aws-serverless.md:911`, and
     `examples/aws-serverless/streaming-openai/README.md:126`. Unrelated to #523; cheap to correct
     here and misleading to leave beside newly-corrected samples.
  8. **The breaking-change note** — see below; it ships here rather than as a docs page.
- **Verify:** no test gate; this PR touches no code. Instead:
  - `grep -ri "transitional\|token delta\|AsyncGenerator\[str" docs/docs .agents/skills` returns
    nothing, and every `path:line` in the inventory below has been visited.
  - `grep -rn 'data: {"delta"\|"delta": ' docs/docs examples` — every remaining hit shows the frame
    shape *with* `event`, and no sample shows a terminal frame carrying a `delta`.
  - `docs/sidebars.js` lists the new AG-UI page. The sidebar enumerates pages explicitly rather than
    autogenerating, so a new `.md` file alone is invisible in the nav.
  - **`docs/versioned_docs/**` is out of scope** — eighteen frozen snapshots, several containing the
    old frame shape. They document released versions where that shape was correct, so changing them
     would make the archive wrong rather than right.

---



## Documentation surfaces — reference

The inventory behind iteration 7, kept as a table so no row is discovered late and so the "no change
needed" calls are on the record. Every row was located by search; the Owner column is uniformly PR 7
and is retained only to make that uniformity explicit rather than accidental.

**Dev skills** (`.agents/skills/`):

| File | Line | What changes | Owner |
|---|---|---|---|
| `ak-dev-architecture/SKILL.md` | 63 | `Runner.stream` is no longer `AsyncGenerator[str, None]`; add `supports_streaming` | PR 7 |
| `ak-dev-architecture/SKILL.md` | 95, 224, 810-814 | `Runtime.stream` — the event write-back and the `delta`/`event` pair | PR 7 |
| `ak-dev-architecture/SKILL.md` | 42 | `Session.Keys` list gains `AGUI_STATE` and its accessors | PR 7 |
| `ak-dev-new-framework-integration/SKILL.md` | 132, 151-156, 160 | "just implement `Runner.stream()`" now means yielding events, with the adapter-state rule | PR 7 |
| `ak-dev-new-framework-integration/SKILL.md` | 378 | checklist item gains `supports_streaming` | PR 7 |
| `ak-dev-testing-conventions/SKILL.md` | 120-123 | the `DummyRunner.stream` snippet yields events, not token strings. **End state only** — a note that bare strings still work is false after PR 6 and would have a reader write a broken double | PR 7 |

**Docs** (`docs/docs/`):

| File | Line | What changes | Owner |
|---|---|---|---|
| `core-concepts/runner.md` | 35, 54, 59, 129 | `stream()` yields events; the `StreamChunk` example gains `event` | PR 7 |
| `integrations/hooks.md` | 210-233 | `on_stream_chunk` still takes `str`, but its return is written back into the event; add the tool-call limit | PR 7 |
| `architecture/execution-flow.md` | 173-193 | the streaming sequence diagram shows `Runner.stream()` returning a bare `delta` and the SSE payload as `{"delta": ..., "done": ...}`; both gain `event`, plus the boundary frames that carry no `delta` | PR 7 |
| `architecture/execution-flow.md` | 366-387 | the WebSocket `STREAM_CHUNK` payload and the execution-mode table carry the same wire shape | PR 7 |
| `architecture/overview.md` | 247-253 | **missed by the original search.** The streaming sequence diagram spells out `delta (str)` and `token dropped`; both describe the pre-#523 loop | PR 7 |
| `core-concepts/runtime.md` | 55-56 | **missed by the original search.** The `stream()` pipeline bullets describe passing each token delta through `on_stream_chunk` and yielding `StreamChunk(delta=...)` per token | PR 7 |
| `advanced/multimodal.md` | — | all five source forms now work; state which are described/stored and which pass through | PR 7 |
| `integrations/overview.md` | — | add AG-UI to the integration list | PR 7 |
| new page under `advanced/` | — | AG-UI: routes, config, the fidelity matrix, `agui_state`, `forwardedProps`, `context`, and the tool-call redaction limit. The matrix is the row that forced this table's Owner column to PR 7 — its content is decided by PRs 4-6 | PR 7 |
| `docs/sidebars.js` | `tutorialSidebar` → `Advanced` category | add the new AG-UI page. The sidebar enumerates every page explicitly rather than autogenerating from the filesystem, so a new `.md` file alone is invisible in the nav | PR 7 |
| `advanced/threads.md` | — | verified: no change. It documents the `Authoriser` AG-UI now shares, but AG-UI adds no thread behaviour | — |

**Examples** (`examples/`) — **this whole surface was missing from the inventory** until PR 1's CI run
failed on the first row. Located by `grep -rln 'data: {"delta"\|"delta": ' examples`:

| File | Line | What changes | Owner |
|---|---|---|---|
| `examples/api/pydanticai-streaming/README.md` | 35-44 | the SSE frame samples gain `event` and the boundary frames. **Also 5-7**: names `run_stream()` / `stream_text(delta=True)` as what drives the stream, which PR 6 replaces — invalidated twice, and the reason this table cannot be split across PRs | PR 7 |
| `examples/api/openai/README.md` | 92-94 | the `curl -N` sample output | PR 7 |
| `examples/aws-containerized/openai-stream/README.md` | 71-74 | `STREAM_CHUNK` samples | PR 7 |
| `examples/aws-containerized/openai-stream-queue-mode/README.md` | 80-83 | `STREAM_CHUNK` samples | PR 7 |
| `examples/aws-serverless/streaming-openai/README.md` | 124-126 | `STREAM_CHUNK` samples, **and** line 126 shows a terminal frame carrying a `delta` — a pre-existing error | PR 7 |
| `examples/api/pydanticai-streaming/app_test.py` | 79 | **not PR 7 — PR 1.** A test, not a doc; it ships with the behaviour that breaks it. Listed here so the row is not mistaken for an omission | PR 1 |
| the other three `mode: stream` examples' test files | — | verified: none exists. Only `pydanticai-streaming` has an `app_test.py` that asserts on frames | — |
| example JS/HTML frontends | — | verified: no change. Zero matches for `.delta` in any example's `.html` or `.js` | — |

Every row is PR 7 apart from the one example *test*, which is PR 1's. Three docs rows and the entire
Examples table were absent until implementation of PR 1 found them:
`architecture/overview.md` and `core-concepts/runtime.md` both describe `Runtime.stream`'s loop but
contain none of the strings the original search looked for, and `examples/` was never searched at all.

**The pattern in all three misses is the same**, and it is worth stating once rather than three times:
the inventory was built by grepping for the *identifiers* the change touches (`StreamChunk`,
`Runner.stream`, `delta`) inside the *directories* assumed to hold documentation (`docs/docs`,
`.agents/skills`). It missed prose that describes the behaviour without naming the identifier, and it
missed documentation living next to code. A wire-format change should instead be inventoried by
searching for the *shape* — here `grep -rn '"delta"' --include="*.md" --include="*.py" .` across the
whole repository — which finds all of them in one pass.

**Verified as needing no change**, by search rather than assumption — zero matches for `StreamChunk`,
`Runner.stream` or `delta` in either:

- `core-concepts/session.md` — the caches and their semantics are unchanged; the new key is additive.
- `core-concepts/tools.md` — the system-tool mechanism is unchanged; only a new capability uses it.

**The breaking change ships as a version/changelog note, not as a docs page.** That is what AK already
does: #500 renamed `text`→`prompt` across public models and handled it exactly this way
(`docs/specs/500-rename-text-prompt-fields/design.md:92`). There is no upgrade guide or migration page
anywhere in `docs/`. The note must keep two audiences apart: a custom `Runner` yielding `str` must
change to yield events; and a frontend reading `delta` keeps working **provided it guards on the
field's presence** — the stream now also carries `message_start` / `message_end` frames, and any frame
whose event is not a `TextDelta` has no `delta` at all, so a client that appends `frame.delta`
unconditionally renders `undefined` twice per response. The earlier claim that such a frontend needs
no change at all was too strong; iteration 1's Verify section records how it was found.

**After the combined merge**, `.github/workflows/auto-sync-skills-docs.yaml` runs over
`.agents/skills/**`, `docs/docs/**`, `docs/sidebars.js` and `docs/docs/agent-skills.md` and opens a
`docs:` PR labelled `auto-skill-doc-sync`. Because the seven PRs merge together, it runs **once against
the complete end state** rather than against intermediate commits — so the fidelity matrix and
`runner.md` are already true when it reads them. Anything it raises is a docs-only follow-up, not
part of this set. It is **not** a substitute for iteration 7: it reacts to what the code says, so with
PR 7 omitted it would be the only thing writing the contract's documentation, unreviewed and after
the fact.
