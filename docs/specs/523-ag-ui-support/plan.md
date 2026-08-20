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
  1. Extend `_extract_attachment` to classify the source and return `is_base64` (§8a). Split
    `data:` URIs into base64 plus their real mime type, dropping the `"image/jpeg"` fallback.
  2. Make `on_run` decide, in one pass over the requests, both what to describe and what travels on,
    retaining anything the hook declined (§8b). **This is the half that is easy to miss** — without it
     a URL attachment is deleted instead of merely undescribed.
  3. Write the new test file, covering all five forms.
  4. **Post-review additions.** Three things came out of PR #648's review:
     - **A `data:` URI with an empty payload is now dropped, not retained.** `_resolve_source` returns
       `Optional[...]`, so `data:image/png;base64,` resolves to `None` and takes the existing
       "no bytes" path — the same one `image_data=""` already took. Previously `not payload` was
       OR-ed with the base64-marker check, so a payloadless URI was classified as not base64 and
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
  5. **The consumed-`id(req)` set was removed, and should not be re-proposed.** The first
    implementation of step 2 split the work across two loops over the same list: one described and
     stored while recording which requests it had taken over, the other consulted that set to decide
     what to strip. Neither loop could be read on its own, and the set needed a docstring paragraph
     explaining why its key was object identity rather than equality. Merging them into one pass puts
     the decision and its consequence on the same line, which removes the set, the `id(req)` key and
     the explanation; the two storage paths became `_describe_stored` and `_store`, with truncation
     stated once in `_described`. It is a pure refactor: **34 of the 35 tests passed unmodified**, and
     the injected prompt text was proven byte-identical across six request shapes. The one deleted
     test existed only to pin the set's meaning. The requirement in §8b is unchanged — a declined
     attachment must still survive into the returned list — only the mechanism moved.
- **Verify:** `uv run pytest tests/test_multimodal_source_forms.py`, then the full suite. Existing
multimodal tests must pass unchanged — they exercise bare base64, which is untouched.



## Iteration 3: The AG-UI integration (PR 3)

The largest iteration, and the only one that needs AG-UI knowledge to review. Ordered so the branch
is testable at each step.

- **Goal:** a compliant AG-UI client can discover agents, start a run, receive the event stream, and
round-trip state.
- **Files:** `core/base.py`, `core/tool.py`, `core/config.py`,
`agui.py` (new — the top-level alias module every integration has, e.g. `thread.py`),
`ak-py/pyproject.toml`, `integration/agui/` (new, including `state.py`), `examples/api/agui/` (new),
`.github/test-config.yaml`, plus four new test files
- **Steps:**
  1. **Cache keys first** — `AGUI_STATE_KEY` in nv_cache plus the two volatile-cache keys in
    `integration/agui/state.py` (§5). Independently testable, and everything else leans on them.
  2. `integration/agui/state.py` — `AGUIState` carrying the four tools (`get_agui_state`,
    `update_agui_state`, `get_forwarded_props`, `get_agui_context`) and their two `SystemTool`
     builders, plus the three cache-key constants this module owns at module scope, since
     `run_input.py` shares them (§5, §6). Docstrings are the LLM-facing tool schema; write them as
     such.
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
  7b. **Module lives under the AG-UI integration.** `integration/agui/state.py` holds the
    four tools, the two prompt sections, `AGUI_STATE_KEY` plus the volatile-cache keys; the
    `agui.state` / `agui.client_context` blocks stay in config. Names stay AG-UI-specific because the
    tools touch AG-UI's fields; placement under `integration/agui/` keeps that naming out of `core/`.
    A wider rename — capability names for the tools, prompt sections, cache keys and config as well —
    A wider rename — capability names for the tools, prompt sections, cache keys and config as well —
    was implemented and then **reverted**. Recorded so it is not re-proposed: the tools genuinely do
    AG-UI work, so protocol-neutral names described them less accurately, not more. State lives in
    `nv_cache` rather than a `Session.Keys` member, so no session-key migration is implied.
    `SystemToolFactory.get_all()` lazy-imports the tools from `integration/agui/state.py`, the
    same way it already reaches outside core for sandbox.
  8. `examples/api/agui/` — a frontend and the config that enables both tool groups. It must show a
    tool call live *and* a state round-trip; only the second is reachable at PR 3, see below.
     - **The "one static HTML file, no build step" constraint did not survive contact, and was
       dropped deliberately.** A single file with runtime-compiled templates is React in name only:
       there are no components to read, no JSX, and nothing to test. The example is now a Vite + JSX
       app under `examples/api/agui/frontend/`, built to `dist/` and served by `app.py`. The AG-UI
       event stream is folded into the whole UI by one pure `reduceEvent(view, event)` that imports
       neither React nor the DOM — which is what makes reasoning, tool calls and a live status strip
       separable components, and what makes them unit-testable with Node's built-in runner and no
       test framework.
     - **The app is TypeScript, and the protocol types come from `@ag-ui/core` rather than being
       written out here.** Hand-copying ~30 event shapes would put a second, drifting definition of the
       wire format in the repo, against a pre-1.0 protocol that is already deprecating its
       `THINKING_*` family; taking the SDK instead type-checks the reducer's branches *and* the
       outbound `RunAgentInput` envelope against the published format. Every use is an `import type`,
       so it is a devDependency and neither it nor its `zod` dependency reaches the bundle — verified:
       zero matches for `zod` in the built asset, whose size moved 198.35 → 198.57 kB. Three decisions
       fell out of it:
       - The transcript is a **discriminated union** (`TextLine | ToolLine`), not one shape with
         optional fields, because `patchLine`'s callers each read only their own kind's fields. The
         single narrowing assumption — a `messageId` names a text line, a `toolCallId` a tool line —
         is asserted once inside `patchLine` instead of at all five call sites.
       - `StateSchema` in the SDK is `z.any()`, deliberately: the state's shape is an agreement between
         one agent and one client, not part of the protocol. So `types.ts` declares this demo's own
         `DemoState` and the `STATE_SNAPSHOT` branch casts to it. That cast, and the one in `sse.ts`
         where `JSON.parse` output is asserted to be an `AGUIEvent`, are the only two in the app and
         both sit exactly on the trust boundary — types cannot check the wire without runtime
         validation, so every consumer of the state reads defensively.
       - The reducer's parameter stays strictly typed and **the test casts from `unknown` instead**.
         The suite deliberately feeds malformed and unknown-version events (`RUN_STARTED` with no
         `threadId`, a `SOMETHING_FROM_0_3`) because surviving them is the contract under test; typing
         that parameter loosely to accommodate them would have destroyed narrowing in every branch.
     - **Tests run on Node's type stripping, not a test framework.** Keeping the "no framework
       installed" property cost `.ts` extensions in import specifiers (`allowImportingTsExtensions`)
       and a Node 22.18 floor in `engines`; vitest would have cost 29 extra packages against the whole
       toolchain's 9. `erasableSyntaxOnly` and `verbatimModuleSyntax` make the stripping requirement
       machine-checked rather than a convention. One tsconfig, not the usual three — `vite.config.ts`
       needs no Node-specific types, so the app and config share it.
     - The type gate was **negative-tested**, not assumed: reintroducing the real `TOOL_CALL_END`
       bug from PR 3 (reading `event.toolCallName`, a field that event does not carry) fails
       `tsc`, as do a `TextLine` passed to `ToolCall` and a snake_cased envelope field. Verified only
       under Node 24.18 locally; the 22.18 floor is where unflagged stripping landed upstream.
     - **A later pass halved the prose and merged the component files** — 924 → 770 lines, 18 files →
       14, and 14 React hook calls → 9. The hook reduction is the substantive part: nothing in the app
       is `React.memo`'d and no React Compiler is configured, so all three `useCallback`s memoized
       identities nothing observed, and the `useRef` they forced (to dodge the stale `view.state` their
       dependency arrays created) went with them. Verified behaviour-preserving by a byte-identical
       headless-Chrome DOM dump and a bundle that moved 198.57 → 198.38 kB. **CopilotKit was evaluated
       and rejected**: its provider takes `agent` as a string naming an agent on a CopilotRuntime, so
       adopting it means a Node service beside `app.py` — breaking single-origin serving, the
       optional-npm property and the CI job — at a cost of 557 packages, one of which (`@scarf/scarf`)
       runs a postinstall phone-home. `@ag-ui/client`'s `HttpAgent` was the near-miss, rejected because
       `rxjs` and `zod` would become the app's first runtime dependencies and an observable would hide
       the POST-and-SSE mechanics the example exists to show. The README points at CopilotKit instead.
     - **The asset route matches names, it does not join them.** CodeQL raised three High
       path-injection alerts against the first version, which built `assets/<Path(filename).name>` and
       leaned on an `is_relative_to` containment check. They were false positives — but a near miss:
       `Path("..").name` is `".."`, not `""`, so the containment check was the only thing stopping it
       and `.name` alone was never sufficient. The route now compares `filename` against the entries
       `iterdir()` yields, so user input never becomes a path segment and no guard has to be trusted;
       the query has no dataflow left to follow either. A regression test sends `/assets/%2e%2e`
       percent-encoded, because httpx normalises a literal `/assets/..` to `/` before it leaves the
       client and would have passed against anything.
     - **A wired capability the demo agent would not reach for.** CI failed on
       `test_client_context_reaches_the_agent_as_tool_output` with the agent replying "I don't know your
       favourite colour". Every link was sound and unit-tested — cache write, tool attachment, prompt
       suffix, cache read — so the failure was the model declining to call `get_agui_context`: the
       planner's instructions framed it as a task-list assistant and told it to keep replies to one
       short sentence. That made it a broken **demo**, not only a broken test, because the README
       twice invites the reader to ask "what time is it for me?". Fixed in two places: the example's
       instructions now put attached context in remit, and the e2e prompt names the tool. Naming it is
       not a weakened assertion — for shared state the *call* is the capability, so model behaviour is
       legitimately load-bearing there; for client context the capability is that entries arrive as
       tool output instead of being flattened into the prompt, and the call is only how you observe
       it. Note what `test_state_round_trip` never proved: the instructions name `update_agui_state`
       themselves, so its passing said nothing about the system-prompt suffix reaching the model.
       PR 4 can replace the string match with an assertion on a `ToolCallStart` named
       `get_agui_context`, which would have made this failure unambiguous.
     - The Node toolchain is **optional**: `build.sh` installs Python only. The UI is `npm run dev`
       (Vite on :5173, proxying `/agui`), or an optional `npm run build` served at `GET /`. No CI job
       sets up Node for this example, and `app_test.py` exercises the AG-UI routes and the asset
       route's 404 paths, never the built page, so nothing in CI depends on a frontend build.
     - "Show a tool call live" **cannot be met at PR 3** — see Verify — and the example does not try
       to fake it. It renders reasoning, tool calls and the live status strip as first-class
       components, tested against hand-written event sequences; they simply stay empty until PRs 4-6
       migrate the adapters. **Nothing in the example says so**, deliberately: the seven PRs merge as
       one stack, so by the time this reaches `develop` the adapters do emit those events and any note
       about "not yet" would be false on arrival — the same born-stale trap as the skills notes in the
       header. A sample-replay button was tried first and removed for exactly that reason.
- **Verify:** `uv run pytest tests/test_agui_*.py` (131 new tests), then the full suite — green with
**no edits to any existing test**, which is the compatibility claim for a purely additive PR.
Manually: run the example, confirm streamed text renders and a `StateSnapshot` arrives. **Tool calls
cannot render yet** — no adapter emits `ToolCallStart` until PR 4, so text arrives here via the
transitional normalization in §4 and the tool-call half of the example is exercised at PR 4. The
example's `reduceEvent.ts` still handles the tool-call events, so PR 4 lights it up with no example change.
  - **The `dict` tool parameter would have shipped broken, and nothing in the plan would have caught
    it.** `update_agui_state(updates: dict)` — the signature §6 specified — makes the OpenAI Agents
     SDK raise `UserError: additionalProperties should not be set for object types` when it builds its
     strict schema, so **every** agent with `agui.state.enabled` failed to *construct*. Found by
     booting the example, not by any unit test: the tool tests call the function directly, and the
     handler tests use scripted runners that never bind a tool. `test_agui_state.py` now asserts
     all four tools bind through `OpenAIToolBuilder`, which is the guard that was missing.
  - **Discovery leaked the system prompt.** The first version returned
    `agent.get_description()` alongside each name; several adapters return the agent's *instructions*
     from it (`framework/openai/openai.py:270`), so the payload contained the whole system prompt
     including the injected system-tool guidance. Now names only, matching
     `AgentRESTRequestHandler.list_agents`.
  - **§9's `ChatService.execute_stream` choice was wrong.** It cannot
    deliver `forwardedProps` or `context` under any persistent session store — see §9 for the two
     facts that combine to make it silently return `{}`. The handler uses `ChatService.prepare_agent_handler` then
     `AgentHandler.run_stream_async` instead, guarded by a test using a deep-copying session store.
  - **An example test is registered in CI** (`.github/test-config.yaml`, `type: api`), because
    iteration 1 established that `uv run pytest` in `ak-py` is not evidence the examples are green.
     It is also the only test anywhere that drives a real adapter through `Runtime.stream`, `to_agui`
     and `EventEncoder` onto a real HTTP surface. Its state-round-trip assertion depends on the model
     actually calling `update_agui_state` — deliberately, since that call *is* the capability.
  - **No new mypy errors** in the three existing files touched: `base.py` 2→2, `config.py` 5→5, and
    `tool.py` 4→**2** (annotating `tools: list[SystemTool]` cleared two pre-existing errors along with
     the two the new branches would have added). All five new modules are clean.
  - **The conformance kit question is answered — there is none.** Four candidate PyPI names all 404,
    and the upstream repository publishes no Python conformance package. Recorded in §*Conformance
     kit* so it is not re-opened.



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
  4. Decisions taken while implementing, recorded because PRs 5 and 6 copy this shape:
     - **Boundaries can only come from OpenAI's raw events, not its run items.** `message_output_created`
       fires once the message is already complete, so it cannot open one. The raw
       `response.output_item.added` / `.done` pair brackets both prose and reasoning — one pair of
       branches, the item's own `type` picking which — and the run-item events are then read *only*
       for `tool_called` / `tool_output`. Mapping `message_output_created` as well would emit every
       message twice; there is a test asserting it stays ignored.
     - **Tool arguments arrive whole, deliberately.** `tool_called` carries complete arguments, so the
       call is opened, filled and closed together. Streaming them per-token was rejected on a verified
       fact: `response.function_call_arguments.delta` carries only `item_id`, **never** `call_id`, so
       progressive args would need a per-run `item_id → call_id` map — and §10 states OpenAI needs no
       memory. A UI showing arguments being typed is not worth making that sentence false.
     - **Reasoning is mapped too**, beyond step 1's letter: three branches keyed off `item_id`, no
       state. `mapping.py` already translates all three to `REASONING_MESSAGE_*`, so without this the
       example's reasoning rendering would stay dead for OpenAI.
     - **LangGraph ids are `event["run_id"]`**, which `langchain_core/runnables/schema.py:124` declares
       required — so it is read directly rather than defensively. A nested model call inside a tool gets
       its own id, which is what makes start/end pairing work with no adapter memory; a test pins that
       two concurrent calls do not share one.
     - **`StepStart`/`StepEnd` are not emitted.** `on_chain_*` fires for every runnable in a LangGraph,
       not only the nodes a reader would call steps, so choosing which to name is its own decision
       rather than part of this mapping.
     - **LangGraph bracketed an empty message on every tool-calling turn, and a review caught it.**
       `on_chat_model_start` / `on_chat_model_end` were mapped directly, but LangChain fires both
       whether or not prose was streamed — so a turn where the model emits only a tool call produced
       `MessageStart` + `MessageEnd` with nothing between. That is exactly what §4 rule 4 restructured
       itself to avoid ("an empty assistant bubble in any AG-UI client"), and the example frontend does
       render it: `reduceEvent.ts` pushes an empty assistant line on `TEXT_MESSAGE_START` and
       `Transcript.tsx` has no empty guard. It was the *common* path for the AG-UI example, whose
       planner calls `update_agui_state` on nearly every turn. **OpenAI never had the bug** —
       `response.output_item.added` fires per output item, so a tool-call-only turn yields a
       `function_call` item and no message boundary — which means the two adapters in one PR disagreed
       on the same protocol. Fixed by copying `Runtime.stream`'s `legacy_started` shape: a
       `started: set[str]` local, `MessageStart` deferred to the first non-empty delta, `MessageEnd`
       only for a call that opened. **The `on_chat_model_start` branch is gone**, which deviates from
       step 2 above — the id is on the stream event, so the branch earned nothing once the boundary
       moved. §10 was corrected too: it claimed ADK was the only adapter needing memory, conflating
       correlation ids with boundary derivation. A set rather than one flag because a tool that calls a
       model nests a second `run_id`; there is a test for that.
     - **Handoffs map, and OpenAI was the only adapter that had to be told.** Raised in review: the
       handoff run items fell through unmapped and nothing recorded whether that was a decision. It was
       not. They are now mapped as `ToolCall*`, which needed only the two names added to the filter —
       `handoff_requested` carries a `ResponseFunctionToolCall` and `handoff_occured` carries
       `{call_id, output}`, so the result correlates on the call's own id. The reason for *that* target
       rather than `StepStart`/`StepEnd`, which is what the review proposed, is cross-adapter
       consistency: a handoff stays an ordinary tool call in every other framework — ADK's
       `TransferToAgentTool` is a `FunctionTool`, Pydantic AI has no handoff primitive so delegation is
       a tool calling an agent — so steps would have left OpenAI disagreeing with three adapters about
       one concept. §10 now carries the full eleven-name ledger rather than the handoff row alone.
     - **One bug found by its own test.** `_tool_arguments` re-serialises LangChain's parsed input dict
       with `json.dumps(default=str)`, and `default=str` runs arbitrary `__str__` — so the encoder can
       raise anything, not just `TypeError`/`ValueError`. The first `except` was too narrow and let an
       exception escape mid-stream, failing a live run over expendable data. Now broad, logged, and the
       call stays bracketed without its arguments.
- **Verify:** `uv run pytest tests/test_openai_runner.py tests/test_langgraph_runner.py`, then the
full suite. The two adapters stop using §4's transitional `str` branch, so
`test_runtime_stream_events.py` must stay green on its own mock runner — it is what still covers that
branch until PR 6 deletes it.



## Iteration 5: Google ADK (PR 5)

- **Goal:** ADK emits events, including boundaries it has to derive.
- **Files:** `framework/adk/adk.py`, `tests/test_adk_runner.py`, `tests/test_tool_adk.py`
- **Steps:**
  1. Stop `continue`-ing on non-partial events — that branch is where function calls and responses
    arrive.
  2. Derive the boundaries: `message_id` as a **local inside** `stream`, set on the first
    `partial=True` and cleared on the first `partial=False`. §10 explains why a `self.` attribute
     would be a cross-session bug rather than a crash.
  3. Map function calls and responses onto the tool-call events.
  4. Update `tests/test_adk_runner.py`, including a test that two concurrent `stream()` calls on the
    same runner instance do not share a `message_id`.
  5. Decisions and corrections taken while implementing:
     - **`tests/test_tool_adk.py` also changes, and §10's test tables did not say so.** It holds two
       tests asserting on `stream()`'s output directly (`test_stream_yields_partial_event_text` and
       `test_stream_skips_non_partial_events`), while §10 lists the file under *must NOT change* —
       true only for the `supports_streaming` property it was listed for. `spec.md` now records both
       the correction and the cause: the changing-tests table was derived by grepping test filenames
       per adapter instead of searching for assertions on `stream()`.
     - **Non-partial text is emitted when no partial ever arrived**, which goes beyond step 1's
       letter. ADK normally sends partials then one aggregated non-partial event whose text must be
       suppressed as a duplicate — but a turn that never streamed would then produce an empty reply,
       and `test_stream_skips_non_partial_events` was asserting exactly that. The fallback is guarded
       on nothing having been sent, so it cannot double up, and that test now pins the new behaviour.
     - **Tool activity closes the reasoning trace, not only answer text** — found in review. A
       thinking model calling a tool straight out of reasoning, with nothing said in between, was
       nesting `tool_call_*` inside an open trace and reusing its id on the resuming thought. OpenAI
       cannot produce that shape, so the two adapters disagreed on ordering for the same concept —
       the same divergence class step 6 fixed for message boundaries. Reproduced, then fixed by
       closing the trace before the tool events; §10's "second trace" sentence is now unconditionally
       true rather than true only when text intervened.
     - **A thought that only arrives whole is emitted, mirroring the text fallback** — found in the
       same review. Reasoning was read from partial events only, so a turn that never streamed lost
       its thinking block while keeping its reply. The guard is *whether any thought streamed this
       turn*, not whether a trace is open: answer text closes the trace on the very event that
       streamed the thought, so an open-trace guard let ADK's repeated aggregate through as a
       duplicate — caught by `test_the_aggregate_re_emits_neither_stream` failing on the first
       attempt.
     - **Tool-call ids come from `FunctionCall.id`, not from `uuid4()`.** ADK generates only the
       `message_id`, because that is the one correlation id it supplies nothing for. A generated
       tool-call id could not be matched to the `FunctionResponse`, so a call with no id emits
       nothing — the same rule PR 4 applied to OpenAI.
     - **A message left open when the stream drains is closed after the loop.** Placed after the
       `async for` and before the write-back, so a client disconnect raises `GeneratorExit` at a
       yield and unwinds past it — no synthetic `MessageEnd` on a disconnect, matching §9.
     - **The concurrency test was negative-tested.** Caching the derived id on the runner instance
       makes it fail on `a_start.message_id != b_start.message_id`; without that check the test would
       have passed against the very bug §10 warns about.
  6. **A self-review caught a tool call nested inside an open text message.** One `Content` can hold
    prose and a function call, and the first version emitted tool events before the boundary handling,
     so that case produced `TEXT_MESSAGE_START → CONTENT → TOOL_CALL_* → TEXT_MESSAGE_END`. OpenAI
     cannot produce that shape, so the two adapters disagreed on the same protocol. Not a proven
     breach — the `ag_ui` SDK ships no verifier and the example frontend copes — but a divergence a
     consumer can trip over, fixed by moving one `for` loop below the branches. Two things fell out of
     it: both `continue`s disappeared, leaving the loop as a decision table, and `_tool_events` stayed
     wired for *every* event rather than only the non-partial ones, because a partial is not proven
     never to carry a call and dropping one silently is worse than emitting it early. The ordering is
     now asserted by a test that was confirmed failing first. The same review also found the `stream`
     docstring claiming non-partial text is never re-emitted while the code emits it as a fallback,
     and a test fixture relying on `MagicMock`'s default empty iteration; §10 records the tool-result
     shape difference the review raised and why it is left alone.
  7. **ADK was emitting a thinking model's reasoning as the assistant's answer.** `_event_text` joined
    the text of every part, but reasoning in ADK is `types.Part.thought` — a flag, not an event — so a
     summary became `TextDelta` and therefore `StreamChunk.delta`, which §4 rule 5 exists to keep it
     out of. Not merely a missing feature: `delta` is what plain-text clients render and what
     `ThreadRecorder` persists, so chain-of-thought was going into the saved reply. Fixed by splitting
     each event's parts into answer and reasoning and deriving a second boundary stream, closed when
     answer text arrives. **Found by a question about ADK's event model, after the self-review had
     already passed** — the review checked which *events* ADK sends and never asked what a `Part` can
     carry, which is the same class of gap as §10's test-table omission. Two things worth keeping:
     the projection was verified through `Runtime.stream`, not just the event list, because rule 5 is
     about `delta` and the event list cannot show it; and three `test_tool_adk.py` fixtures had to set
     `thought = False` explicitly, since a bare `MagicMock` attribute is truthy and would classify
     every fixture's text as reasoning — a real `types.Part` defaults it to `None`.
  8. **Handoffs cost no code, and that was the finding worth recording.** Raised for ADK after PR 4
     mapped OpenAI's handoff run items: nothing was needed here, because `TransferToAgentTool` is a
     `FunctionTool`, so a transfer arrives as an ordinary `function_call` and step 3's mapping already
     carries it. Tests were still added, because §10's cross-adapter claim rested on reading the SDK
     rather than on anything the suite checked — one of them reads the tool's name off
     `TransferToAgentTool` instead of a literal, so an upstream rename fails rather than silently
     invalidating the claim. OpenAI remains the only adapter that needed a branch, since it is the
     only one that lifts handoffs out of its own tool stream.
- **Verify:** `uv run pytest tests/test_adk_runner.py tests/test_tool_adk.py`, then the full suite.



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
  6. Decisions and corrections taken while implementing:
     - **`PartStartEvent.index` is not usable as an id, correcting §10.** It is scoped to one response
       and the SDK documents that a repeat *replaces* the part, so a tool-then-answer run would hand two
       messages the same id. Pydantic AI needs a local after all — `open_parts`, mapping a live index to
       the id it opened with — which makes §10's "only ADK and LangGraph remember anything" claim wrong:
       it is three of four. A test drives two `part_start`s at index 0 and asserts two distinct ids.
     - **`function_tool_call` is ignored, for OpenAI's `message_output_created` reason.** The part events
       already open, fill and close the call, so mapping the tool event too would emit every call twice.
       Tested by feeding both and asserting one `ToolCallStart`.
     - **The history write-back reads the terminal `agent_run_result` event**, captured as it passes,
       rather than the old context manager's value: `run_stream_events` yields the `AgentRunResult` as
       its final item instead of exposing it on the CM.
     - **One of step 5's three doubles failed *silently*, not loudly.** The step predicted a
       `ValidationError` in all three. True for `test_runtime.py` and `test_pipeline_request_handler.py`,
       but `ChatService.execute_stream` **catches** a mid-stream raise and converts it to an error chunk,
       so `test_chat_service_core.py`'s acting-user tests kept passing while the stream was broken — they
       asserted only the `seen` side effect. Migrated, and given an assertion that no chunk carries an
       error so a broken double cannot pass again. The lesson generalises: a test that asserts only a
       side effect cannot tell a working stream from a swallowed exception.
     - **`core/__init__.py` must not be import-sorted.** Its order is load-bearing — `.model` before
       `.chat_service`, or `service.py`'s `from ..core import AgentRequest` hits a partially initialised
       module — which is why the Makefile passes `--skip` for it. Running `isort` directly over `src/`
       bypasses that and breaks every import in the package; use `make lint`.
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
| `ak-dev-architecture/SKILL.md` | 42 | Document AG-UI state in `nv_cache` (not a new `Session.Keys` member) | PR 7 |
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
| the fidelity matrix's handoff row | — | LangGraph surfaces a handoff only when the application built it as a *tool* (`on_tool_start`/`on_tool_end`); a bare `Command(goto=...)` edge fires `on_chain_*`, which PR 4 declined as too noisy. OpenAI, ADK and Pydantic AI surface it unconditionally, as a tool call | PR 7 |
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
| `examples/api/agui/**` | — | **not PR 7 — PR 3.** A new example ships with its own README, and it is written against the AG-UI surface rather than the SSE frame shape PR 7 corrects elsewhere. Its one forward reference (the docs page carrying the fidelity matrix) resolves when PR 7 lands in the same stack | PR 3 |

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
