# #706 — the changes, file by file

> **Status: superseded in part — read `design.md` first.**
>
> This file records the investigation as it stood. It was written **before PR #678 merged** and
> before the design changed direction, so parts of it are now wrong rather than merely dated. Kept
> because it records *why* routes were considered, which is this file's job. Where it and
> `design.md` disagree, **`design.md` is authoritative.**
>
> What is superseded:
>
> - **The streaming gap.** `PostHook.on_stream_chunk` no longer exists. `on_stream_event`
>   (`core/hooks.py:94`) is called at `core/runtime.py:343` for *every* event. Only "`on_run` is
>   never called on a streamed run" survives, and the "design fork" below is closed — the design
>   takes the structured-event route.
> - **The REST contract.** This file prescribes an *additive* structured field beside `result`.
>   `design.md` Decision 3 landed somewhere else again: **one field, switched by the label** —
>   `result` carries the object when the reply has a `media_type` and the string it carries today
>   when it does not. No second field, and not a breaking change. The prescription below is close in
>   spirit but is not a drop-in: it gates on reply *type* where the decision gates on *media type
>   presence*, and it adds a field where the decision reuses `result`.
> - **"The only flattening site."** False. `core/service.py:156` also stringifies, which is why A2A,
>   MCP and the CLI never receive a typed reply at all.
> - **The `a2ui` capability.** Every proposal below for an `agentkernel/a2ui/` package, an
>   `_A2UIConfig`, a `core/tool.py` prompt contributor, a factory registration or an `a2ui` extra is
>   now an explicit **Non-goal** (`design.md` Decision 7). A2UI lives in an application post-hook.
> - **Scope.** MCP and the CLI are not mentioned anywhere below; both are scoped in `design.md`
>   (MCP in, CLI out permanently).
> - **Line citations** below are historical, taken at `9d3d3a40`; `design.md` is verified against
>   `develop` at `80936df9`.

Companion to [`README.md`](README.md), which argues *why* the work splits into a payload layer and
a carriage layer. This file is the *what*: every file that has to change, in the order that lets
each piece land on its own.

Line numbers verified on `feature/706-a2ui-transport-agnostic` at `9d3d3a40`. Two things are marked
**[unverified]**: the `a2a-sdk` and `ag-ui-protocol` symbol names, because neither package is
installed in the environment this was written in. Check both against the pinned versions before
writing code against them.

---

## Piece 1 — let a reply say what it is holding

Nothing else can be built honestly first: a transport cannot label a payload it cannot identify.

**`ak-py/src/agentkernel/core/model.py`**
- `AgentReplyAny` (`:129`) — add an optional media-type field, defaulted to `None`.
- `from_output` (`:146`) — accept and pass through the media type, defaulted to `None`.
- **Do not touch `__str__`** (`:142`). It serialises `content` only, so every existing string
  consumer sees exactly what it sees today.

All six adapters keep calling `from_output` with no media type and are unaffected
(`openai.py:193`, `langgraph.py:409`, `pydanticai.py:162`, `smolagents.py:175`, `adk.py:247`,
`crewai.py:387,389`). Only the A2UI post-hook in piece 4 ever sets the field.

**Tests** — new `ak-py/tests/test_model_reply_any.py`: default is `None`, the field round-trips,
`__str__` output is byte-identical to today's.

---

## Piece 2 — stop flattening at the response builder

**`ak-py/src/agentkernel/core/chat_service.py`**

> **[corrected]** `design.md` Decision 3 reuses `result` rather than adding a field, and gates the
> object form on the reply carrying a `media_type` — so an unlabelled structured reply keeps the
> string exactly as today. The "two fields disagree on any non-plain value" objection below is why
> there is no second field; the gate is why it is not a breaking change either.

- `ResponseBuilder.build_response` (`:317`) — keep `"result": str(result)` exactly as it is, and
  *add* the structured content when the reply is an `AgentReplyAny`, plus the media type when set.
  Additive only: existing clients keep reading `result`.
- The field name is a permanent public REST contract. Decide it deliberately.

> **[corrected]** not the only place — `core/service.py:156` also stringifies, one layer lower,
> which is why A2A, MCP and the CLI never receive a typed reply.

**Reach — verified, and larger than it looks.** This one function is the only place non-streaming
replies are stringified anywhere outside A2A. It serves:

| Caller | Surface |
|---|---|
| `core/chat_service.py:587,605` | REST |
| `integration/thread/thread_chat.py:123,128` | Conversation threads |
| `pipeline/agent_runner.py:44` → same `ChatService.process_chat_request` | Queue pipeline → WebSocket + async mode |

The pipeline's response dict travels the output queue and leaves over WebSocket as a dict already
(`pipeline/ws/base.py:108` takes `message: dict`). **No WebSocket-specific change is needed** —
one edit here covers REST, WebSocket, async mode and threads.

**Tests** — `test_chat_service_core.py` (structured reply carries the new field; text reply
unchanged), plus a pipeline/WS frame assertion in `test_akresponsehandler.py`.

**Docs** — `docs/docs/api/rest-api.md`: the new response field.

---

## Piece 3 — A2A data parts

**`ak-py/src/agentkernel/api/a2a/a2a.py`**
- `A2A.Executor.execute` (`:49`) — today every reply is `new_agent_text_message(str(response), ...)`.
  Branch on the reply type: an `AgentReplyAny` becomes a message carrying a data part with
  `response.content` and its media type; everything else keeps the current text path.
- The error path (`:52`) stays text.
- **[unverified]** the exact `a2a-sdk` symbols (`DataPart`, `Part`, whether there is a
  `new_agent_parts_message` helper or the `Message` is built directly) against
  `a2a-sdk>=0.3.6` (`ak-py/pyproject.toml:167`).

**`ak-py/src/agentkernel/core/builder.py`**
- `A2ACardBuilder.build` (`:38-48`) is the single place every agent card is built — no per-adapter
  work. Note it already sets `default_output_modes=["json"]` (`:44`) while the executor sends only
  text, so **the card is already inaccurate today**; this piece makes it true. Add the A2UI media
  type to the list when the capability is enabled.

**Behavioural change to declare in `design.md`:** this changes A2A output for *all* structured
replies, not only A2UI. That is the intended unopinionated outcome, but it is not a silent detail.

**Tests** — no `test_a2a*.py` exists yet; add one. Cover both branches and the error path.

**Docs** — `docs/docs/api/a2a-server.md`.

---

## Piece 4 — the `a2ui` capability itself

New package **`ak-py/src/agentkernel/a2ui/`** (top level, like `sandbox/` — it is a capability, not
an integration, because it adds no surface of its own):
- `catalog.py` — load catalogs, build the prompt suffix.
- `hooks.py` — `A2UIPostHook(PostHook)` plus `A2UIPostHookFactory.get()`, copying
  `SandboxPreHookFactory` (`sandbox/hooks.py:134-149`) exactly: return the real hook when enabled,
  a no-op otherwise, and a no-op on any initialisation failure — the hook chain must never break
  the runtime.

**`ak-py/src/agentkernel/core/config.py`**
- New `_A2UIConfig` beside `_SandboxConfig` (`:758`): `enabled`, the `agents` filter, catalog
  settings.
- Register on `AKConfig` (`:856+`).

**`ak-py/src/agentkernel/core/tool.py`** — the one place the shape does not already fit.
`get_system_prompt_suffix` joins `SystemTool.description` strings (`:243`), so a prompt is only
reachable by hanging it on a tool. A2UI has no tool. Two options:
- **(a)** register a description-only `SystemTool` whose `func` is never bound. There is precedent
  (the sandbox puts a whole prompt section on one tool), but the type says "tool" and it is not one.
- **(b)** add a prompt-contributor path alongside `get_all`, so the suffix is tool descriptions
  *plus* registered prompt-only contributions. **Recommended** — roughly ten lines, honest, and
  every future prompt-only capability wants it.

**`ak-py/src/agentkernel/core/runtime.py`**
- `_get_system_post_hooks` (`:63`) returns the literal `[OutputGuardrailFactory.get()]`. Add
  `A2UIPostHookFactory.get()`. The pre-hook line directly above (`:56`) already chains three
  factories, so this is the established shape and a one-line change.

**`ak-py/pyproject.toml`**
- New `a2ui` extra near `agui` (`:88`). Version pin is a decision, not a detail: A2UI was v0.9.1
  with 1.0 a release candidate at the time of the #523 survey — re-check what is current.

**Three questions this piece cannot dodge** (from the #523 survey §6):
1. **Catalog ownership** — does AK bundle a starter catalog, require the application to supply one,
   or only pass one through? This is the difference between a small capability and an ongoing
   maintenance surface.
2. **Render-only, or interactive?** A2UI defines callbacks from the rendered UI back to the agent.
   Render-only is a defensible v1, but it has to be *stated* — a UI with dead buttons is worse than
   no UI.
3. **Context cost** — a prompt-injected catalog is paid on every request. Size it.

**Tests** — new `test_a2ui_hook.py`, `test_a2ui_catalog.py`; the config block in `test_config.py`;
the prompt-suffix path in whichever test covers `SystemToolFactory`.

**Docs** — new `docs/docs/advanced/a2ui.md` (sits beside `sandbox.md` and `multimodal.md`), its
sidebar entry, and `docs/docs/core-concepts/configuration.md`.

---

## Piece 5 — AG-UI

Two sub-changes, and the first is a genuine design fork, not a mapping job.

### 5a — a streamed run has no final reply

> **[corrected]** stale — `on_stream_chunk` no longer exists; `on_stream_event` receives every
> event (`core/hooks.py:94`, called at `core/runtime.py:343`). Only the `on_run` half still holds.

`Runtime.stream` (`core/runtime.py:233-286`) runs `PostHook.on_stream_chunk` on text deltas and
**never calls `PostHook.on_run`**. So the A2UI hook from piece 4 does not fire on an AG-UI run at
all.

- **(a) A final-reply hook on the streaming path.** Before the terminal
  `yield StreamChunk(done=True)` (`:286`), assemble the accumulated text into a reply, run the
  post-hook chain's `on_run`, emit the result. Reuses piece 4 unchanged and keeps A2UI on all six
  frameworks. Cost: a new contract on the streaming path, and it must not double-apply the output
  guardrail that already ran per chunk.
- **(b) A structured `StreamEvent` variant** in `core/event.py` that adapters emit mid-stream.
  Matches A2UI's advertised incremental parse-and-heal, but needs per-adapter work and reaches only
  the four streaming adapters.

Not exclusive. (a) first is the cheaper order.

### 5b — the mapper has no case for it

`AGUIMapper.to_agui` (`integration/agui/mapping.py`) returns `None` for anything with no AG-UI
equivalent (`:64`). Add a case above that fallback mapping the structured payload onto AG-UI's
custom event, whose `value` field is already structured. AK emits none today.

**[unverified]** the `ag_ui.core` custom-event class name against `ag-ui-protocol>=0.1.16`
(`ak-py/pyproject.toml:88`).

**Tests** — `test_agui_mapping.py`, `test_akagentrunner_stream.py`, `test_chat_service_streaming.py`.

**Docs** — `docs/docs/integrations/agui.md`, `docs/docs/api/agui-server.md`.

---

## Across all pieces

- **Skills and docs sync.** The repo runs `auto-sync-skills-docs.yaml` and expects guidance to
  track implementation. A new capability touches `.agents/skills/ak-dev-architecture` and the
  bundled `ak-add-capabilities` skill. Use `ak-dev-sync-skills-from-branch` and
  `ak-dev-sync-docs-from-branch` rather than editing by hand.
- **Formatting** is black + isort at line length 150; `make lint-check-all` is what CI runs.
- **Ordering claim worth re-testing:** pieces 1–3 contain no A2UI code. If a change in them only
  makes sense for A2UI, it belongs in piece 4 instead — that is the test that the split is real.
