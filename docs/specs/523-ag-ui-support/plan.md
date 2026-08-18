# #523: AG-UI protocol support — Implementation Plan

Build order for [spec.md](spec.md). **Six PRs** and one non-PR closing step, two independent roots;
§-references point at `spec.md` sections rather than restating them.


| Iteration | PR                                                | Depends on          |
| --------- | ------------------------------------------------- | ------------------- |
| 1         | PR 1 — the streaming contract                     | —                   |
| 2         | PR 2 — attachment source forms                    | —                   |
| 3         | PR 3 — the AG-UI integration                      | 1, 2                |
| 4         | PR 4 — OpenAI + LangGraph                         | 1                   |
| 5         | PR 5 — Google ADK                                 | 1                   |
| 6         | PR 6 — Pydantic AI, and the end of the transition | 1, and 4 + 5 merged |


Iterations 1 and 2 can run in parallel. So can 4, 5 and 6's adapter work; only iteration 6's *last
step* waits on 4 and 5.

**There is no separate documentation iteration.** Every docs and skills surface this change
invalidates is updated inside the PR that invalidates it, as a step of that iteration — a merged PR
must never leave the docs describing behaviour it just changed. The full inventory, including the
surfaces verified as needing *no* change, is at the end of this document as reference material rather
than as work.

---



## Iteration 1: The streaming contract (PR 1)

- **Goal:** the event model exists, `Runner.stream` is typed for it, `StreamChunk` carries `event`,
and nothing has changed behaviour — the adapters still yield `str` and the whole suite passes
untouched.
- **Files:** `core/events.py` (new), `core/model.py`, `core/base.py`, `core/runtime.py`,
`framework/crewai/crewai.py`, `framework/smolagents/smolagents.py`,
`tests/test_stream_events.py` (new), `tests/test_runtime_stream_events.py` (new)
- **Steps:**
  1. Add `core/events.py` — the twelve event classes and the `StreamEvent` discriminated union (§1).
  2. Add `event: StreamEvent | None` to `StreamChunk`, after `delta` (§2). `delta` stays a plain
    settable field — **not** a computed field; §2 explains which existing test decides this.
  3. Add the `supports_streaming` **property** to `Runner` (default `True`) and widen `stream`'s
    return annotation (§3). Declare `False` on `CrewAIRunner` and `SmolagentsRunner`; leave their
     bodies raising.
  4. Rewrite the `Runtime.stream` loop (§4): text extraction, hook chain, write-back into the event,
    `None` drops the whole chunk, and the transitional `str` branch carrying the comment that names
     PR 6.
  5. Write the two new test files.
  6. Docs and skills, all invalidated by this PR's contract change:
     `core-concepts/runner.md` (35, 55, 59, 122-136), `integrations/hooks.md` (176-188),
     `architecture/execution-flow.md` (173-193 and 366-387),
     `ak-dev-architecture/SKILL.md` (61, 90-93),
     `ak-dev-new-framework-integration/SKILL.md` (158, 376),
     `ak-dev-testing-conventions/SKILL.md` (109).
- **Verify:** `cd ak-py && uv run pytest` — green with **zero edits to existing tests**. That is the
gate, not a nicety: an edit anywhere else means the projection in §4 is wrong.



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
  4. Docs: `advanced/multimodal.md` — all five source forms now work; say which are described and
     stored and which pass through untouched.
- **Verify:** `uv run pytest tests/test_multimodal_source_forms.py`, then the full suite. Existing
multimodal tests must pass unchanged — they exercise bare base64, which is untouched.



## Iteration 3: The AG-UI integration (PR 3)

The largest iteration, and the only one that needs AG-UI knowledge to review. Ordered so the branch
is testable at each step.

- **Goal:** a compliant AG-UI client can discover agents, start a run, receive the event stream, and
round-trip state.
- **Files:** `core/base.py`, `core/agui_state.py` (new), `core/tool.py`, `core/config.py`,
`ak-py/pyproject.toml`, `integration/agui/` (new, 5 modules), `examples/api/agui/` (new),
`docs/docs/`, plus four new test files
- **Steps:**
  1. **Session key first** — `Session.Keys.AGUI_STATE` and its three accessors (§5). Independently
    testable, and everything else leans on it.
  2. `core/agui_state.py` — the three tool functions and their two `SystemTool` builders (§6).
    Docstrings are the LLM-facing tool schema; write them as such.
  3. Config: `_AGUIConfig` with the nested `state` and `forwarded_props` blocks (§Config changes),
    then the two `SystemToolFactory` branches (§7). Both flags default `False`.
  4. `integration/agui/authoriser.py` and `envelope.py` (§9). Envelope mapping is pure and testable
    without a server.
  5. `integration/agui/mapping.py` — `to_agui` plus its exhaustiveness test. Write the test with the
    mapping, not after.
  6. `integration/agui/handler.py` — routes, identity, run lifecycle, `StateSnapshot` (§9).
  7. `agui` extra in `pyproject.toml`; confirm the `ag-ui-protocol` floor against the released
    package before pinning.
  8. `examples/api/agui/` — one static HTML file, no build step. It must show a tool call live *and*
    a state round-trip, and ship the config that enables both tool groups.
  9. Docs: the fidelity matrix, the `thread_id`→`session_id` note, the ignored-`tools` non-goal,
    `forwardedProps` being read-only and pull-based, AG-UI state's session lifetime, and the
     tool-call redaction limit (§4 deferred note).
- **Verify:** `uv run pytest tests/test_agui_*.py`, then the full suite. Manually: run the example,
attach a file, confirm a tool call renders and a `StateSnapshot` arrives.



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
`tests/test_pydanticai_runner.py`, `tests/test_runtime_stream_events.py`
- **Steps:**
  1. Replace `run_stream(...)` + `stream_text(delta=True)` with `run_stream_events()`.
  2. Re-plumb the two things that live inside the old `async with` block — session-message
    bookkeeping and `_store_framework_context` — so both still run only after the stream drains
     normally, inside the `try`, never in `finally` (§10).
  3. Update `tests/test_pydanticai_runner.py`, keeping the `framework_context` round-trip assertions
    intact — that is the regression this rewrite most easily causes.
  4. **Only once iterations 4 and 5 have merged:** delete the transitional `str` branch from
    `Runtime.stream`, and add a test asserting a `str`-yielding runner now fails loudly.
- **Verify:** `uv run pytest` — full suite. Grep `core/runtime.py` for the transitional comment and
confirm it is gone.

> If review returns PR 6 before 4 and 5, merge its adapter half and move step 4 to whichever PR lands
> last. The gate travels with the step, not the number.



## Documentation surfaces — reference

Not an iteration and not a PR. This is the inventory behind the docs steps in iterations 1, 2 and 3,
kept in one place so no PR author has to rediscover it and so the "no change needed" calls are on the
record. Every row was located by search.

**Dev skills** (`.agents/skills/`):

| File | Line | What changes | Owner |
|---|---|---|---|
| `ak-dev-architecture/SKILL.md` | 61 | `Runner.stream` is no longer `AsyncGenerator[str, None]`; add `supports_streaming` | PR 1 |
| `ak-dev-architecture/SKILL.md` | 90-93 | `Runtime.stream` — the event write-back and the `delta`/`event` pair | PR 1 |
| `ak-dev-architecture/SKILL.md` | 42 | `Session.Keys` list gains `AGUI_STATE` and its accessors | PR 3 |
| `ak-dev-new-framework-integration/SKILL.md` | 158 | "just implement `Runner.stream()`" now means yielding events, with the adapter-state rule | PR 1 |
| `ak-dev-new-framework-integration/SKILL.md` | 376 | checklist item gains `supports_streaming` | PR 1 |
| `ak-dev-testing-conventions/SKILL.md` | 109 | the `DummyRunner.stream` snippet yields events, not token strings | PR 1 |

**Docs** (`docs/docs/`):

| File | Line | What changes | Owner |
|---|---|---|---|
| `core-concepts/runner.md` | 35, 55, 59, 122-136 | `stream()` yields events; the `StreamChunk` example gains `event` | PR 1 |
| `integrations/hooks.md` | 176-188 | `on_stream_chunk` still takes `str`, but its return is written back into the event; add the tool-call limit | PR 1 |
| `architecture/execution-flow.md` | 173-193 | the streaming sequence diagram shows `Runner.stream()` returning a bare `delta` and the SSE payload as `{"delta": ..., "done": ...}`; both gain `event` | PR 1 |
| `architecture/execution-flow.md` | 366-387 | the WebSocket `STREAM_CHUNK` payload and the execution-mode table carry the same wire shape | PR 1 |
| `advanced/multimodal.md` | — | all five source forms now work; state which are described/stored and which pass through | PR 2 |
| `integrations/overview.md` | — | add AG-UI to the integration list | PR 3 |
| new page under `advanced/` | — | AG-UI: routes, config, the fidelity matrix, `agui_state`, `forwardedProps` | PR 3 |

PR 1 owns most of it, which is expected: it is the PR that changes the contract everything else
describes.

**Verified as needing no change**, by search rather than assumption — zero matches for `StreamChunk`,
`Runner.stream` or `delta` in either:

- `core-concepts/session.md` — the caches and their semantics are unchanged; the new key is additive.
- `core-concepts/tools.md` — the system-tool mechanism is unchanged; only a new capability uses it.

**The breaking change ships as a version/changelog note, not as a docs page.** That is what AK already
does: #500 renamed `text`→`prompt` across public models and handled it exactly this way
(`docs/specs/500-rename-text-prompt-fields/design.md:92`). There is no upgrade guide or migration page
anywhere in `docs/`. The note must keep two audiences apart: a custom `Runner` yielding `str` must
change to yield events; a frontend reading `delta` needs no change at all.

**After the combined merge**, `.github/workflows/auto-sync-skills-docs.yaml` runs over
`.agents/skills/**`, `docs/docs/**`, `docs/sidebars.js` and `docs/docs/agent-skills.md` and opens a
`docs:` PR labelled `auto-skill-doc-sync`. Because the six PRs merge together, it runs **once against
the complete end state** rather than against intermediate commits — so the fidelity matrix and
`runner.md` are already true when it reads them. Anything it raises is a docs-only follow-up, not
part of this set.
