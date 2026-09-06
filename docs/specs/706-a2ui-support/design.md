# #706: A2UI support — one payload capability, structured carriage on every surface

A2UI is a payload format, not a transport, so this is two things: a capability that teaches an agent
to produce validated A2UI JSON, and the ability for AK's existing surfaces to carry a *structured*
reply instead of `str()`-ing it. The carriage half contains no A2UI code and is useful to every
current `AgentReplyAny` user; A2UI is then one payload riding it, identified by a media type the
surfaces carry but never interpret.

Supporting research: [`research/README.md`](research/README.md) (payload/carriage framing, per-surface
gap analysis), [`research/changes.md`](research/changes.md) (file-by-file), and the protocol survey at
[`../523-ag-ui-support/research/a2ui.md`](../523-ag-ui-support/research/a2ui.md).

## Motivation

- **An AK agent can only reply with text at the surfaces.** An application wanting a form, a table or
  a chart must build bespoke rendering per agent and parse prose to drive it.
- **Every mechanism the payload half needs already exists**, built for other reasons:
  - Per-capability config block with an `agents` filter — `core/config.py:758` (`_SandboxConfig`),
    `:845` (`_AGUIConfig`).
  - System-prompt injection — `SystemToolFactory.get_system_prompt_suffix` (`core/tool.py:224`),
    built from `get_all` (`:179`).
  - Reply post-processing — `PostHook.on_run` (`core/hooks.py:51`).
  - A structured reply type — `AgentReplyAny(content: dict)` (`core/model.py:129`).
  - Optional-dependency gating — the extras pattern (`ak-py/pyproject.toml:88`, `:167`).
- **Structured replies already reach all six adapters**, so A2UI needs no adapter work and no
  streaming: `openai.py:215`, `langgraph.py:424`, `pydanticai.py:178`, `smolagents.py:176`,
  `adk.py:262`, `crewai.py:388,390`. AG-UI reaches four (only those four declare
  `supports_streaming`).
- **The surfaces are what is missing, and they fail differently:**
  - `ResponseBuilder.build_response` emits `{"result": str(result)}` for every reply type including
    `AgentReplyAny` (`core/chat_service.py:317`). Verified: this is the **only** place non-streaming
    replies are stringified outside A2A — no other `str(reply)` exists across `api/`, `pipeline/` or
    `integration/agui/`.
  - It is also shared. REST (`chat_service.py:587,605`), conversation threads
    (`integration/thread/thread_chat.py:123,128`) and the queue pipeline
    (`pipeline/agent_runner.py:44` → the same `ChatService.process_chat_request`) all route through
    it, and the pipeline's dict leaves over WebSocket as a dict already
    (`pipeline/ws/base.py:108` takes `message: dict`). One change covers four surfaces.
  - A2A hardcodes `new_agent_text_message(str(response), ...)` (`api/a2a/a2a.py:49`). There is no
    `DataPart` path, so the wrapping A2UI actually specifies is unreachable. JSON-as-a-string does
    not substitute: an A2UI-aware A2A client does not recognise a text message.
  - The A2A agent card already advertises `default_output_modes=["json"]`
    (`core/builder.py:44`) while the executor sends only text — **the card is inaccurate today.**
  - No member of the `StreamEvent` union (`core/event.py:131`, twelve members) can carry a dict;
    every one carries text and ids.
- **`AgentReplyAny` cannot say what kind of payload it holds.** A transport cannot emit
  `application/json+a2ui` unless the reply names the format, so without this each surface must guess
  or import A2UI to sniff the dict — which is the opinion this design exists to avoid.

```mermaid
graph TD
    CAP["a2ui capability<br/>(catalog in prompt → validate the JSON back)"]
    REP["AgentReplyAny<br/>content: dict + media_type"]
    A2A["A2A<br/>DataPart(mimeType)"]
    RB["ResponseBuilder<br/>structured field + label"]
    EV["StreamEvent<br/>structured member"]
    REST["REST"]
    WS["WebSocket"]
    ASY["Async mode"]
    TH["Threads"]
    AGUI["AG-UI custom event"]

    CAP -->|produces| REP
    REP --> A2A
    REP --> RB
    REP --> EV
    RB --> REST
    RB --> WS
    RB --> ASY
    RB --> TH
    EV --> AGUI
```

## Requirements

### Ordering and dependencies

- Delivered as **five PRs**, in this order. Each lands independently and is useful on its own.
- **PRs 1–3 contain no A2UI code.** They are structured-reply carriage. If a change in them only
  makes sense for A2UI, it belongs in PR 4 instead — this is the test that the split is real.
- **This work merges after #678 (streaming post-hooks) and #696 (HITL).** Both are open at the time
  of writing; the requirements below assume their designs as merged and must be re-checked if either
  changes:
  - #678 deletes `PostHook.on_stream_chunk` and replaces it with `on_stream_event(session, requests,
    agent, event) -> StreamEvent | list[StreamEvent] | None`, called for every event including
    boundaries, with a list return emitting several events in place of one. It also states
    **`PostHook.on_run` on streamed runs is a non-goal** with its own issue — so PR 5 must not take
    that route.
  - #696 adds `AgentReplyPaused` as a *subclass* of `AgentReplyAny` (the `AgentReply` union at
    `core/model.py:126` is unchanged) and a `RunPaused` member to the `StreamEvent` union, and
    reopens `ResponseBuilder.build_response` to express a third outcome.
- PRs 1–4 have no hard dependency on either. **PR 5 requires #678 merged.**

### PR 1 — the reply carries its media type

- Add an optional media-type field to `AgentReplyAny` (`core/model.py:129`), typed `str | None`,
  defaulted `None`.
  - Naming decision: `media_type` (RFC 6838 term), matching the MIME parlance every consumer uses.
- `from_output` (`core/model.py:146`) accepts and passes it through, defaulted `None`.
- **`__str__` (`core/model.py:142`) is not touched.** It serialises `content` only, so every existing
  string consumer sees byte-identical output. This is testable and must have a regression test.
- **Semantics, stated so no surface invents its own:**
  - Written only by whoever produces the payload. Never inferred, never sniffed from the dict.
  - **AK never parses it.** Not validated against a registry, not a routing key.
  - It is **not** the discriminator for what kind of reply this is — that is `type`, which #696 uses
    for `"paused"`. The two are orthogonal axes: `type` says what outcome this is, `media_type` says
    what format `content` is in.
  - A surface that must emit something when it is unset falls back to `application/json`.
- All six adapter construction sites keep calling `from_output`/`AgentReplyAny(...)` unchanged and
  leave it `None`. `AgentReplyPaused` (#696) inherits it, defaulted, and nothing sets it there.

### PR 2 — the response builder carries structured content

- `ResponseBuilder.build_response` (`core/chat_service.py:317`) emits the structured content when the
  reply is an `AgentReplyAny`, plus the media type when set.
  - **Additive only.** `"result": str(result)` stays exactly as it is; existing clients keep reading
    it. A client that knows nothing of this change sees no difference.
  - The new field name is a permanent public REST contract — see Open questions.
- Rebase onto #696, which reopens the same function for the `PAUSED` outcome. By then it already
  branches on the reply rather than only stringifying, so this is one more branch.
  - A paused reply is an `AgentReplyAny` subclass, so it will also match this branch. State
    explicitly whether the structured field is emitted for it, or suppressed in favour of #696's
    `interruptions` — see Open questions.
- **No WebSocket-, async- or thread-specific change.** All three reach this function (Motivation),
  and the pipeline's dict is already a dict on the WebSocket frame.

### PR 3 — A2A data parts

- `A2A.Executor.execute` (`api/a2a/a2a.py:49`) branches on the reply type instead of always calling
  `new_agent_text_message(str(response), ...)`:
  - `AgentReplyAny` → a message carrying a data part with `response.content`, labelled with
    `media_type` when set and `application/json` otherwise.
  - Every other reply type keeps the current text path, byte-for-byte.
  - The error path (`a2a.py:54`) stays text.
- `A2ACardBuilder.build` (`core/builder.py:38-48`) is the single place every agent card is built, so
  there is no per-adapter work. Add the A2UI media type to `default_output_modes` when the capability
  is enabled; the existing `"json"` entry (`:44`) becomes accurate rather than aspirational.
- **Behavioural change, to be stated in the PR, not discovered:** this changes A2A wire output for
  *all* structured replies, not only A2UI. That is the intended unopinionated outcome.
- The exact `a2a-sdk` symbols (`DataPart`, `Part`, whether a `new_agent_parts_message` helper exists)
  are **unverified** — neither package was installed when this was written. Check against the pinned
  `a2a-sdk>=0.3.6` (`ak-py/pyproject.toml:167`) before `spec.md`.

### PR 4 — the `a2ui` capability

- New top-level package `ak-py/src/agentkernel/a2ui/`, shaped like `sandbox/` and `schedule/`:
  a capability, not an integration, because it mounts no surface of its own.
  - `catalog.py` — load component catalogs, build the prompt section.
  - `hooks.py` — `A2UIPostHook(PostHook)` plus `A2UIPostHookFactory.get()`, copying
    `SandboxPreHookFactory` (`sandbox/hooks.py:134-149`): the real hook when enabled, a no-op
    otherwise, and a no-op on any initialisation failure — the hook chain must never break the
    runtime.
- Coupling: `core/` reaches `a2ui/` **only lazily, inside enabled-checks** — the sandbox/schedule
  precedent already used at `core/tool.py:179` and `core/runtime.py:63`. Nothing in `a2ui/` imports
  `framework/`, `integration/`, `deployment/` or `api/`.
- Config: new `_A2UIConfig` beside `_SandboxConfig` (`core/config.py:758`), registered on `AKConfig`.
  - `enabled: bool = False` — inert when off: no tools, no prompt text, no imports.
  - `agents: Optional[list[str]] = None` — the standard per-capability filter, honoured through
    `SystemToolFactory._agent_allowed`.
  - Catalog settings — shape depends on Open questions.
- **Prompt injection needs one small core change.** `get_system_prompt_suffix` joins
  `SystemTool.description` strings (`core/tool.py:243`), so a prompt is only reachable by hanging it
  on a tool, and an A2UI catalog has no tool.
  - Add a prompt-contributor path alongside `get_all`, so the suffix is tool descriptions *plus*
    registered prompt-only contributions.
  - Rejected alternative: registering a description-only `SystemTool` whose `func` is never bound.
    There is precedent (the sandbox carries a whole prompt section on one tool), but the type says
    "tool" and it is not one — and `ToolBuilder.bind()` derives names from `func.__name__`, so a
    dummy function is a live footgun.
- `Runtime._get_system_post_hooks` (`core/runtime.py:63`) returns the literal
  `[OutputGuardrailFactory.get()]`; add `A2UIPostHookFactory.get()`. The pre-hook line above (`:55`)
  already chains three factories, so this is the established shape.
- New `a2ui` extra in `ak-py/pyproject.toml`, near `agui` (`:88`).
- **Hook behaviour must be specified, not left to the implementation:**
  - Valid payload → an `AgentReplyAny` with `content` set to the parsed payload and `media_type` set.
  - Invalid payload → see Open questions. Whatever is chosen, the hook must never raise into the
    runtime.
  - Reply types other than the model's structured/text output pass through untouched.

### PR 5 — AG-UI

- Add a **structured member to the `StreamEvent` union** (`core/event.py:131`) able to carry a dict
  plus its media type.
  - It must honour the union's stated invariant that no field carries a framework-native object.
  - #696's `RunPaused` establishes that adding a member is a normal move, not a new pattern.
- Delivery uses #678's `on_stream_event` hold-and-release, with no further Runtime change:
  the A2UI hook returns `None` per `TextDelta` while accumulating in the session's volatile cache,
  then at the closing boundary returns `[<structured event>, <the boundary event>]`.
  - The buffer lives in the volatile cache, never on `self` — hook instances are process-wide
    (`core/runtime.py:59-64`).
- `AGUIMapper.to_agui` (`integration/agui/mapping.py`) gains one case above its `case _` fallback
  (`:64`), mapping the structured event onto AG-UI's custom event, whose `value` field is structured.
  - The `ag_ui.core` custom-event symbol is **unverified** — check against the pinned
    `ag-ui-protocol` before `spec.md`.
- **Not in scope here:** running `PostHook.on_run` on a streamed run. #678 files that as its own
  issue; PR 5 must not implement it as a side effect.

### Verification

- Unit tests per PR, in `ak-py/tests/`, following `ak-dev-testing-conventions`.
  - PR 1's load-bearing test is the **regression**: `str(AgentReplyAny(...))` unchanged.
  - PR 3 needs a new `test_a2a_*.py` — no A2A test file exists today.
  - PR 4 covers: valid parse, invalid payload, disabled → no-op hook, `agents` filter honoured,
    prompt suffix contains the catalog.
  - PR 5 extends `test_agui_mapping.py` and the #678 streaming tests.
- **One cross-surface parity test** (new): one structured reply, asserted to arrive with the same
  dict and label on REST, WebSocket, A2A and AG-UI. Nothing like it exists. This is what makes the
  unopinionated claim checkable rather than asserted, and it is what catches a future surface
  silently regressing to `str()`.
- Examples, reusing what exists rather than adding a frontend:
  - PRs 1–2 → extend `examples/api/openai_structured/`, which already returns a structured reply
    through a `PostHook` over REST.
  - PR 4 → new backend-only `examples/api/a2ui/`, no frontend. This is the example that demonstrates
    A2UI arriving over plain REST with no UI framework involved.
  - PR 5 → extend `examples/api/agui/`, whose React frontend already has an event reducer and
    `node --test` unit tests. Do not build a second frontend.

## Non-goals

- **Running `PostHook.on_run` on streamed runs.** #678's own non-goal, with its own issue.
- **Streaming *partial* A2UI.** The capability parses a whole payload at a boundary; A2UI's
  incremental parse-and-heal is not implemented, though #678's hold-and-release is the mechanism a
  later change would use.
- **A2UI for HITL pauses.** A pause is produced by the framework interrupting a tool call, not
  authored by the model, so this capability's prompt-and-parse loop does not apply. A deterministic
  interruption-to-form renderer would mean AK deciding what an approval card looks like — the exact
  opinion this design avoids — and #696 already maps interruptions onto AG-UI's native `Interrupt`.
  One narrow case survives (an agent that itself writes the form it is asking a human to fill in) and
  is raised in Open questions rather than built here.
- **A frontend, or an A2UI renderer of any kind.** The client owns its component catalog; that is the
  protocol's premise.
- **Changing `StreamChunk.delta`, `AgentReply` union membership, or any framework adapter.**
- **Guardrail inspection of A2UI payloads.** Output guardrails see the reply as they do today; no
  A2UI-aware guardrail behaviour is added.

## Open questions

1. **REST field name (PR 2).** The key carrying the structured content is a permanent public
   contract. `data`? `content`? `structured`? Decide deliberately, once.
2. **Structured field on a paused reply (PR 2 × #696).** `AgentReplyPaused` subclasses
   `AgentReplyAny`, so it matches the same branch. Emit the structured field for it, or suppress it
   in favour of #696's `interruptions`? Emitting duplicates the same facts in two shapes; suppressing
   means the branch is not purely type-driven.
3. **Catalog ownership (PR 4).** Does AK bundle a starter catalog, require the application to supply
   one, or only pass one through? This is the difference between a small capability and an ongoing
   maintenance surface.
4. **Invalid payload behaviour (PR 4).** When the model returns something that is not valid A2UI:
   fail loud (an error reply), or degrade to the text reply the model produced? Degrading is friendly
   and hides a broken agent; failing is honest and turns a model slip into a user-visible error.
5. **Render-only, or interactive (PR 4)?** A2UI defines actions and callbacks from the rendered UI
   back to the agent. Render-only is a defensible v1 but must be *stated* — a UI with dead buttons is
   worse than no UI.
6. **Version pin (PR 4).** A2UI was v0.9.1 with 1.0 a release candidate at the time of the #523
   survey. Pin, or wait for 1.0? Re-check what is current.
7. **A2A behaviour change (PR 3).** Confirm the maintainers accept that A2A output changes for all
   structured replies, not only A2UI.
8. **Coordination with #696 on `PausedInterruption.payload`.** That field is in #696's design with
   **no stated meaning**. If it is defined as an agent- or author-supplied payload describing the
   interruption (plus a label saying how to read it), the one surviving HITL case above is served
   with no new field — a LangGraph node calling `interrupt({...})` with an A2UI dict needs none of
   this capability. If it is instead defined as a framework hint blob, that use is closed off by
   convention. **The ask is to settle its meaning while #696 is still design-only**, not to reserve
   anything for this issue; the field itself could be added later cheaply either way.
