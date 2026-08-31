# AG-UI: protocol survey and Agent Kernel gap analysis

Supporting research for #523. Protocol facts marked **[docs]** come from vendor documentation
fetched 2026-08-14 and were not exercised locally; code facts were read on `develop` at `1693d2e0`.

## 1. What AG-UI is

AG-UI (Agent–User Interaction Protocol) is an open, MIT-licensed, **event-based** protocol that
standardizes how an agent backend talks to a user-facing frontend. It is not a UI toolkit and not
an agent framework: it is a fixed vocabulary of ~25 event types plus a request envelope, so any
compliant frontend can drive any compliant agent. **[docs]**

The shape of a run, in one sentence: the client POSTs a `RunAgentInput` JSON body, the server
replies with a stream of typed events (SSE by default) that begins with `RunStarted` and ends with
`RunFinished` or `RunError`. **[docs]**

- Transport is deliberately unspecified — SSE, WebSockets, and webhooks are all named as valid
  carriers; the reference Python server example is a FastAPI `POST /` returning a
  `StreamingResponse` with `media_type` taken from an `EventEncoder` built off the request's
  `Accept` header. **[docs]**
- Licensed MIT; ~15.3k GitHub stars; actively developed. **[docs]**

### 1.1 The request envelope

`RunAgentInput` (Python SDK field names, snake_case): **[docs]**

| Field | Type | Note for AK |
|---|---|---|
| `thread_id` | `str` | Maps to AK's `session_id` |
| `run_id` | `str` | No AK equivalent; AK has no per-run identifier on the chat surfaces |
| `parent_run_id` | `Optional[str]` | No AK equivalent |
| `state` | `Any` | Closest AK analogue is the reserved `framework_context` key / session caches |
| `messages` | `List[Message]` | AK rebuilds history from its session store, not from the request |
| `tools` | `List[Tool]` | **No AK equivalent** — see §3.3 |
| `context` | `List[Context]` | `description`/`value` pairs; closest AK analogue is `AgentRequestAny` |
| `forwarded_props` | `Any` | Free-form passthrough |

Message roles: `developer`, `system`, `assistant`, `user`, `tool`, `activity`, `reasoning`. **[docs]**

### 1.2 The event vocabulary

Grouped as the docs group them. AK's current streaming surface can populate the **bold** ones and
nothing else (see §3.1).

| Category | Events |
|---|---|
| Lifecycle | **`RunStarted`**, **`RunFinished`**, **`RunError`**, `StepStarted`, `StepFinished` |
| Text message | **`TextMessageStart`**, **`TextMessageContent`**, **`TextMessageEnd`**, **`TextMessageChunk`** |
| Tool call | `ToolCallStart`, `ToolCallArgs`, `ToolCallEnd`, `ToolCallResult`, `ToolCallChunk` |
| State | `StateSnapshot`, `StateDelta` (RFC 6902 JSON Patch), `MessagesSnapshot` |
| Activity | `ActivitySnapshot`, `ActivityDelta` |
| Reasoning | `ReasoningStart`, `ReasoningMessageStart`, `ReasoningMessageContent`, `ReasoningMessageEnd`, `ReasoningMessageChunk`, `ReasoningEnd`, `ReasoningEncryptedValue` |
| Special | `Raw`, `Custom` |
| Draft | `MetaEvent` |

`Custom` (`name` + `value`) is the documented extension point, and is the natural carrier for an
A2UI payload — see [`a2ui.md`](a2ui.md) §4.2. **[docs]**

### 1.3 Ecosystem: the packages that already exist

This matters because four of AK's six supported frameworks already have an AG-UI implementation
someone else maintains. **[docs]**

| AK adapter | AG-UI support tier | Package |
|---|---|---|
| Pydantic AI | 1st party | `pydantic-ai-slim[ag-ui]` (pulls `ag-ui-protocol`, `starlette`) |
| Google ADK | 1st party | `ag-ui-adk` |
| LangGraph | Partnership | `ag-ui-langgraph` |
| CrewAI | Partnership | `ag-ui-crewai` |
| OpenAI Agents SDK | Community, "in progress" | — |
| Smolagents | None found | — |

Base Python SDK: `pip install ag-ui-protocol`, exposing `ag_ui.core` (events + types) and
`ag_ui.encoder` (`EventEncoder`). Pydantic AI documents a floor of `ag-ui-protocol >= 0.1.10`. **[docs]**

Pydantic AI's integration is the most instructive of these, because it has already solved problems
AK will hit: client-supplied tools become agent tools; `RunAgentInput.context` entries are fed to
the model **as tool output rather than as instructions**, explicitly to blunt prompt injection;
client-submitted system prompts are stripped by default (`manage_system_prompt='server'`); a client
disconnect surfaces server-side as `asyncio.CancelledError`. **[docs]**

## 2. Prior decision in this repo

#531 (the Pydantic AI adapter) explicitly listed AG-UI as a **non-goal**, at
`docs/specs/531-introduce-pydanticai-framework/design.md:243`:

> "The AG-UI protocol integration — AK already has REST/WebSocket/MCP/A2A frontends; a second
> framework-specific UI protocol is redundant with 'frontends depend on core, never the reverse.'"

Read precisely, that rejected **wiring one framework's AG-UI package into its adapter** — i.e.
Route A below. It is not an argument against AK growing its own AG-UI frontend alongside REST/WS/
MCP/A2A; if anything the quoted principle ("frontends depend on core, never the reverse") argues
*for* Route B/C/D and *against* Route A. `design.md` should state this reading explicitly so the
new design doesn't read as reversing a settled decision.

## 3. Where Agent Kernel stands today

### 3.1 AK's streaming vocabulary is three fields wide

`StreamChunk` (`ak-py/src/agentkernel/core/model.py:173-176`) is the entire event vocabulary AK has:

```python
class StreamChunk(BaseModel):
    delta: str | None = None
    done: bool = False
    error: str | None = None
```

That is `TextMessageContent`, `RunFinished`, and `RunError` — and nothing else. There is no
representation for a tool call, a step, state, or reasoning.

**Verified by execution, not by reading:** `Runtime.stream` constructs
`StreamChunk(done=True, session_id=session.id)` at `ak-py/src/agentkernel/core/runtime.py:257`, but
`StreamChunk` has no `session_id` field and no `model_config`, so Pydantic v2's default
`extra='ignore'` silently drops it — `StreamChunk(done=True, session_id='abc').model_dump()` returns
`{'delta': None, 'done': True, 'error': None}`. The session id reaches clients only because
`ResponseBuilder.stream_chunk` re-attaches it from a separate argument
(`ak-py/src/agentkernel/core/chat_service.py:318-320`). Harmless today, but any spec that says
"`StreamChunk` carries the session id" would be wrong, and the same silent-drop trap will bite an
event-enrichment refactor.

SSE framing lives in one place — `ResponseBuilder.stream_chunk`
(`chat_service.py:310-321`) emits `data: {json}\n\n`. An AG-UI encoder would sit at exactly this
seam.

### 3.2 The runners already have the events and throw them away

This is the central technical finding, and it makes AG-UI much cheaper than it first looks.

`Runner.stream` is typed `AsyncGenerator[str, None]` (`ak-py/src/agentkernel/core/base.py:355`), so
every adapter is contractually obliged to discard everything that is not a text token:

- **OpenAI** (`framework/openai/openai.py:224-229`): calls `Runner.run_streamed(...)` and iterates
  `result.stream_events()` — the SDK's full event stream — then keeps only
  `event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent)`. Tool
  call items, handoffs, and agent-updated events are already arriving and are dropped by the filter.
- **Google ADK** (`framework/adk/adk.py:274-286`): iterates `runner.run_async(...)` events and
  `continue`s on anything where `event.partial` is falsy, then joins the text parts. ADK function
  calls/responses arrive on non-partial events and are dropped.
- **LangGraph** (`framework/langgraph/langgraph.py:420`) and **Pydantic AI**
  (`framework/pydanticai/pydanticai.py:174`) follow the same yield-strings shape.
- **CrewAI** (`framework/crewai/crewai.py:410-416`) and **smolagents**
  (`framework/smolagents/smolagents.py:186-192`) raise `NotImplementedError`. **Their in-code
  reasons are stale** (corrected 2026-08-14, see §3.2.1) — both SDKs stream today; it is AK's two
  adapters that do not.

#### 3.2.1 The CrewAI and smolagents "no streaming" comments are out of date

`crewai.py:412` says "CrewAI does not support SSE streaming" and `smolagents.py:188` says
"smolagents does not support SSE streaming". Both claims were true when written and are no longer
true of the pinned dependency versions: **[docs]**

- **CrewAI** added streaming in v1.10.1 (early 2026); `ak-py/pyproject.toml` pins
  `crewai>=1.15.0`, so it is available. Construct the crew with `stream=True` and `kickoff()`
  yields `CrewStreamingOutput` chunks carrying `content` (text delta), `chunk_type`
  (`TEXT` | `TOOL_CALL`), a `tool_call` object with `tool_name`/`arguments`, plus `task_name`,
  `task_index`, and `agent_role`. CrewAI also has an event bus emitting tool-use
  started/finished/error and LLM-streaming-chunk events. Notably, `chunk_type` is already close to
  the event union R-C would define.
- **smolagents** supports both token-level streaming (`stream_outputs=True` on the model) and
  step-level streaming (`run(stream=True)` / `_step_stream()` yielding `ChatMessageStreamDelta`
  during a step and `ActionStep`/`FinalAnswerStep` between steps). AK pins `smolagents>=1.0.0`,
  a loose floor — **the exact minimum version exposing this API was not verified** and must be
  pinned before the spec relies on it.

Consequence for the design: **Route C can reach all six adapters, not four.** The ceiling in the
coverage matrix is AK's adapter code, not the frameworks. Route B is still four, because it consumes
the existing `Runner.stream` which those two adapters refuse.

Neither SDK's streaming API was exercised locally; both bullets are documentation claims.

Post-hooks see the same narrow view: `PostHook.on_stream_chunk` takes and returns a `str`
(`core/runtime.py:248-254`).

**Consequence for the design:** the information AG-UI's tool-call and step events need is already in
memory at `openai.py:226` and `adk.py:274`. The expensive part of AG-UI support is not the HTTP
endpoint or the event encoder — it is widening the `Runner.stream` contract so that information
survives to the frontend.

### 3.3 Client-supplied tools have nowhere to go

`RunAgentInput.tools` is a first-class AG-UI concept — the frontend declares tools the *client*
will execute. AK's agent registry is populated once at startup: `Runtime.register`
(`core/runtime.py:128-136`) is called by `Module.load`, and `Runtime.agents()`
(`core/runtime.py:121-126`) returns that static dict. There is no per-request tool injection path,
and `ToolBuilder.bind` (`core/tool.py:153-162`) binds functions to framework-native tool objects at
build time.

Supporting AG-UI frontend tools therefore means either (a) declaring them out of scope for v1 and
ignoring the field, or (b) inventing per-request tool augmentation — a genuinely new capability in
AK, not a translation layer. This is the single largest scoping decision in #523.

### 3.4 Mounting a new protocol surface is a solved problem

AK has a clean precedent for exactly this: A2A and MCP are config-gated frontends assembled in
`RESTAPI.build_app` (`ak-py/src/agentkernel/api/http.py:131-143`) — `a2a.enabled` appends routers,
`mcp.enabled` mounts a sub-app at `/mcp`. Their config blocks are small and uniform
(`_A2AConfig` at `core/config.py:110-114`, `_MCPConfig` at `core/config.py:117-126`, both defaulting
`enabled: False`).

The extension ABC is `RESTRequestHandler` (`api/handler.py:15-33`), whose only contract is
`get_router() -> APIRouter`. Auth applies automatically via router dependencies
(`api/http.py:64`, `add_auth_handlers` at `api/http.py:149-178`). Optional dependencies follow the
existing extras pattern in `ak-py/pyproject.toml:23-172` — an `agui` extra pinning `ag-ui-protocol`
is the obvious shape.

**But note the pipeline interaction.** Since #495, `RESTAPI.run()` delegates to the queue pipeline
`IOHandler` only when *all three* hold: `cls is RESTAPI`, `handlers is None`, and the transport
resolves to `in_memory` (`api/http.py:99-106`). Mounting an AG-UI handler explicitly means passing
`handlers=[...]`, which **switches the whole process off the pipeline** — including for the ordinary
REST routes. The design must choose: AG-UI as a direct-mode-only surface, AG-UI taught to the
pipeline as a second request-handler shape, or AG-UI mounted through
`get_default_handlers()`/config rather than an explicit `handlers` argument. Getting this wrong
silently regresses queue-mode behavior for everything else in the app.

## 4. Four routes, with the trade-off that decides between them

### Route A — delegate to the per-framework AG-UI packages

Wire `ag-ui-adk`, `ag-ui-langgraph`, `ag-ui-crewai`, `pydantic-ai-slim[ag-ui]` into their adapters
and let each own its AG-UI endpoint.

- **For:** near-zero mapping work; best possible event fidelity per framework; someone else
  maintains it.
- **Against:** each package drives its framework's agent *directly*, which means the request never
  passes through `Runtime.run`/`Runtime.stream` — so guardrails, the multimodal pre-hook, session
  storage, conversation threads, tracing, and every user pre/post hook are bypassed. Session and
  state become the AG-UI package's, not AK's. Behavior would differ per framework. Two of six
  frameworks get nothing. And it is what #531:243 already rejected.
- **Verdict:** not viable as the primary route. Possibly useful as a documented escape hatch for
  someone who wants raw framework fidelity and no AK semantics.

### Route B — AG-UI frontend over the existing `StreamChunk` contract

A new `RESTRequestHandler` that accepts `RunAgentInput`, calls `ChatService.execute_stream`, and
translates: `RunStarted` on entry, `TextMessageStart`/`Content`/`End` from `delta`, `RunError` from
`error`, `RunFinished` on `done`.

- **For:** small and self-contained; no changes to `core/base.py`, any adapter, or any existing
  behavior; every AK cross-cutting concern (guardrails, multimodal, threads, session) keeps working
  because it goes through `Runtime`; works today for the four streaming frameworks.
- **Against:** emits ~6 of ~25 event types. No tool-call visibility — which is most of why teams
  adopt AG-UI. CrewAI/smolagents still unsupported. Risks shipping something that is technically
  AG-UI-compliant and practically disappointing.

### Route C — widen the runner streaming contract, then map

Change `Runner.stream` to yield a typed AK event union (text delta, tool-call start/args/end/result,
step, reasoning, state) instead of `str`; adapters stop filtering; `Runtime.stream` and
`PostHook.on_stream_chunk` carry the richer type; the AG-UI handler becomes a thin encoder.

- **For:** the only route that reaches AG-UI's actual value. The source events already exist at the
  adapter boundary (§3.2), so this is unwrapping, not inventing. It also improves AK's own SSE and
  WebSocket streaming, tracing, and thread recording — AG-UI just becomes the first consumer.
- **Against:** touches a public ABC (`Runner.stream`) and all six adapters; needs a back-compat
  story for user-written runners and for `PostHook.on_stream_chunk`'s `str` signature; interacts
  with #495's chunk fan-out (`StreamAgentRunner` currently fans out one queue message per chunk with
  dedup suffixes, which assumes chunks are cheap and text-shaped). Largest blast radius of the four.

### Route D — B then C, staged (suggested default)

Ship Route B as iteration 1 behind an `ag_ui.enabled` config flag, with the event-mapping layer
written against an internal seam rather than against `StreamChunk` directly. Then enrich per
framework under Route C, one adapter at a time, with AG-UI event coverage growing as each lands.

- **For:** a usable AG-UI surface early; the risky contract change is incremental and
  framework-by-framework rather than a single flag-day refactor; each iteration leaves the branch
  green (the #495 Phase A pattern).
- **Against:** the intermediate state is a partial protocol implementation, which needs honest
  documentation — "AG-UI text streaming supported; tool-call events not yet emitted" — rather than
  an unqualified "AG-UI supported" claim.

## 5. Questions `design.md` must answer, not assume

1. **Frontend tools** (§3.3): does v1 ignore `RunAgentInput.tools`, or does AK grow per-request tool
   augmentation? This drives scope more than anything else.
2. **Pipeline interaction** (§3.4): direct-mode-only, or taught to the #495 pipeline? A wrong answer
   silently disables queue mode for the whole app.
3. **State** (`StateSnapshot`/`StateDelta`): mapped onto the reserved `framework_context` key, onto
   session caches, or declared out of scope? Note that `framework_context` round-trip fidelity is
   already per-framework (full for OpenAI/Pydantic AI, partial for ADK/smolagents/LangGraph,
   unsupported for CrewAI), so AG-UI state sync would inherit that unevenness.
4. **Message history**: AG-UI clients send `messages` and expect `MessagesSnapshot`; AK rebuilds
   history server-side from its session store. Does AK trust the client's list, ignore it, or
   reconcile? Ignoring is safest and should be stated, not left implicit.
5. **Non-streaming frameworks**: what does an AG-UI run look like on CrewAI/smolagents — a 501, or a
   degenerate single-message run?
6. **Prompt-injection posture**: does AK adopt Pydantic AI's rules (context as tool output, client
   system prompts stripped)? These are security defaults, not cosmetics.
7. **Version pinning**: which `ag-ui-protocol` version, and what happens when the frontend is newer
   than the server?

## Sources

- [AG-UI introduction](https://docs.ag-ui.com/introduction)
- [AG-UI events reference](https://docs.ag-ui.com/concepts/events)
- [AG-UI Python core types](https://docs.ag-ui.com/sdk/python/core/types)
- [AG-UI server quickstart](https://docs.ag-ui.com/quickstart/server)
- [ag-ui-protocol/ag-ui on GitHub](https://github.com/ag-ui-protocol/ag-ui)
- [Pydantic AI AG-UI integration](https://pydantic.dev/docs/ai/integrations/ui/ag-ui/)
- [ag-ui-adk on PyPI](https://pypi.org/project/ag_ui_adk/)
- [ag-ui-langgraph on PyPI](https://pypi.org/project/ag-ui-langgraph/)
- [ag-ui-crewai on PyPI](https://pypi.org/project/ag-ui-crewai/)
