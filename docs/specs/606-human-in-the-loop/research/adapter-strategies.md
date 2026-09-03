# How each adapter should handle pause / persist / resume

Companion to [`framework-hitl-survey.md`](framework-hitl-survey.md), which establishes what each
framework offers natively. This file maps those mechanisms onto Agent Kernel's adapters: what
each adapter must do, what in the current code stands in the way, and how durable the result
actually is.

All `path:line` citations are against the `develop` branch at the time of writing and were read,
not recalled.

---

## What every adapter has in common today

Three properties of the current adapters shape the whole design.

### 1. Every runner swallows everything

All six `run()` methods end in a catch-all that converts any exception into a text reply:

| Adapter | `except` site |
|---|---|
| OpenAI | `openai.py:218` |
| LangGraph | `langgraph.py:429` |
| Pydantic AI | `pydanticai.py:184` |
| Google ADK | `adk.py:224` |
| CrewAI | `crewai.py:397` |
| smolagents | `smolagents.py:181` |

Each is `except Exception as e: return AgentReplyText(response=user_facing_error_message(e), ...)`.
A framework that signals a pause **by raising** would therefore be reported to the user as an
error string, and the run would look completed. Issue #606's "does not swallow the pause" is
precisely this.

Only Pydantic AI's `CallDeferred` / `ApprovalRequired` are raised *by user tool code* and caught
by the framework itself, so in practice none of the four target frameworks raises a pause across
the adapter boundary. The bigger risk is the second property.

### 2. Pauses that are *returned* are silently discarded

Where a framework returns the pause as data, the adapters throw that data away while extracting
text:

- **LangGraph** — `ainvoke` returns normally with `__interrupt__` in the result dict. The adapter
  reads `result["messages"][-1]` (`langgraph.py:427`) and returns its text. On a paused graph the
  last message is whatever preceded the interrupt, so **the user gets a plausible-looking but
  wrong answer** and the graph stays parked in the checkpointer forever. This is the worst
  failure mode of the six, because nothing looks broken.
- **Google ADK** — `get_response()` iterates events and keeps only `is_final_response()` text
  (`adk.py:220-229`). `event.long_running_tool_ids` is never inspected, so a pending
  long-running call or an `adk_request_confirmation` call is dropped and the reply is empty or
  partial.
- **OpenAI** — the adapter reads `.final_output` off the `RunResult` (`openai.py:208`) and never
  looks at `.interruptions`.
- **Pydantic AI** — the adapter reads `result.output` (`pydanticai.py:171,178-182`).
  `DeferredToolRequests` is a **dataclass, not a `BaseModel`** (verified —
  [`verification.md`](verification.md)), so `AgentReplyAny.from_output` returns `None`
  (`model.py:157-161`) and the adapter falls through to `str(result.output)`
  (`pydanticai.py:182`) — the user gets an `AgentReplyText` holding a dataclass repr, not a
  structured reply.

### 3. Pause state has a natural home already

`Session` persists every non-volatile top-level key through `SessionStore.store()`
(`runtime.py:228`), serialised with `pickle` (`core/session/serde.py:2,24,36`). The reserved-key
pattern with dedicated accessors already exists for `framework_context`
(`base.py:41-48,187-214`), added by #526. A paused-run record is the same shape of problem and
should reuse that pattern rather than invent a second one.

The **only** hard constraint this imposes: whatever a framework hands back as its pause payload
must be **picklable**. All four target payloads are (JSON dicts, jsonable message lists, id
strings) — but this must be asserted, not assumed, exactly as `_ensure_framework_context_picklable`
does today (`base.py:329-348`).

---

## OpenAI Agents SDK

**Verdict: strongest fit. Full durable pause/resume, both modes.**

### Pause

After `Runner.run(...)` returns, check `result.interruptions` before reading `.final_output`
(`openai.py:208`). Non-empty ⇒ pause.

### Persist

`result.to_state()` → `state.to_json()`. That JSON dict is the opaque payload written to the
session. Also store the **agent name**, because `RunState.from_json(agent, stored)` requires the
original starting agent and AK resolves agents by name from `Runtime.agents()`.

### Resume

Rebuild with `RunState.from_json(agent.agent, stored)`, apply the caller's decisions with
`state.approve(item, always_approve=...)` / `state.reject(item, rejection_message=...)`, then
`await Runner.run(agent.agent, state)`. Note this is the **same `Runner.run` entry point** the
adapter already calls, with a `RunState` in place of the input — so resume reuses almost the
entire existing `run()` body.

### Streaming

Documented as supported: drain `stream_events()` to completion, then check
`RunResultStreaming.interruptions`, and resume with `Runner.run_streamed(agent, state)`. The AK
adapter already drains the stream fully (`openai.py:256-262`), so the check slots in right where
`_store_framework_context` is called at `openai.py:266-267`.

### Adapter-specific problems to solve

1. **`needs_approval` is not reachable through AK's tool binding.** AK tools are plain Python
   functions wrapped by the OpenAI `ToolBuilder`; nothing today passes `needs_approval`. Either
   the builder grows a way to mark a function as gated, or users must define OpenAI-native tools
   themselves. **This is the single biggest open question for this adapter** and applies equally
   to Pydantic AI and ADK.
2. **Multimodal runs pass no session.** `_get_run_input` returns `(message_content, None)` for
   anything but a single text message (`openai.py:181-184`), so a paused multimodal run has no
   SDK session to resume against. Needs an explicit decision: refuse to pause, or accept the
   different resume semantics.
3. **`framework_context` collides with `RunState` context serialization.** AK injects the #526
   context as `context=produced` (`openai.py:206-208`) and the SDK documents context
   serialization as "intentionally conservative" — mapping contexts round-trip, custom types need
   explicit serializers. AK's context is constrained to a `dict` (`base.py:292-297`), so the
   common case round-trips, but the interaction must be tested rather than assumed.
4. **`_schema_version`** on `RunState` means a pause can outlive an SDK upgrade and fail to
   restore. The resume path needs a real error for that, not a traceback.

---

## LangGraph

**Verdict: strongest fit, and the least new machinery — AK already owns the checkpointer.**

The decisive finding: `LangGraphRunner._prepare_session_and_messages` **assigns AK's own
checkpointer onto the user's compiled graph** on every run:

```
session_config = LangGraphSessionConfigModel(configurable=LangGraphSessionConfigurable(thread_id=session.id))
lg_session = self._session(session)
agent.agent.checkpointer = lg_session.checkpointer
```
(`langgraph.py:368-370`)

That `CheckPointer` is described in its own docstring as "a pickle-serializable checkpointer"
(`langgraph.py:53-55`) and is held on the `LangGraphSession` stored under the framework key
(`langgraph.py:341`), so it is persisted with the AK session. `thread_id` is `session.id`.

**Everything `interrupt()` needs is therefore already in place** — a checkpointer, a stable
thread id, and durability through AK's own session store. Two consequences worth stating
plainly:

- Users get durable interrupts on Redis/DynamoDB/Valkey sessions **for free**, without
  configuring a LangGraph checkpointer.
- AK **overwrites** any checkpointer the user compiled their graph with. That is pre-existing
  behaviour, but HITL makes it load-bearing and it must be documented.

### Pause

After `ainvoke` (`langgraph.py:414-417`), check for `__interrupt__` in the result **before**
`result["messages"][-1]` at line 427. Each `Interrupt` carries `.value` and `.id`.

### Persist

Nothing framework-specific to serialise — the checkpointer already holds it. The AK paused record
needs only the interrupt ids and their `.value` payloads, so the caller knows what is being
asked.

### Resume

`await agent.agent.ainvoke(Command(resume=value), config)` with the **same config**, i.e. the
same `thread_id` — which AK derives from `session.id`, so it is automatically correct. Multiple
interrupts resume by id map.

### Streaming

The adapter uses `astream_events(..., version="v2")` (`langgraph.py:469-473`). The `.interrupts` /
`.interrupted` attributes the docs describe belong to the newer `stream_events(version="v3")`
surface. On v2 the pause must be detected after the stream drains — and the adapter **already
calls `aget_state(config)` at that exact point** (`langgraph.py:481`) for framework-context
write-back, so pause detection has a natural, already-written home. Whether to instead migrate to
v3 is a real decision with blast radius beyond this issue.

### Adapter-specific problems to solve

1. **AK cannot make a user's graph interruptible.** `interrupt()` is called from inside the
   user's own node, and `LangGraphModule` takes already-compiled graphs
   (`langgraph.py:642,657`). AK's job here is strictly to *not lose* the interrupt — which is
   the honest and correct division of labour, and worth stating as such.
2. **Node re-execution on resume** is LangGraph's documented behaviour, not something AK can
   hide. It goes in the user-facing docs.
3. `result["messages"][-1]` would raise `IndexError` or return a stale message on a graph that
   interrupts before producing any message — another reason the `__interrupt__` check must come
   first, not as a fallback.

---

## Pydantic AI

**Verdict: strong fit, and the most explicitly typed pause of the four.**

### Pause

`DeferredToolRequests` arrives as `result.output` (`pydanticai.py:171`). Detection is a clean
`isinstance` check — but it must be placed **before** `AgentReplyAny.from_output(result.output,
prompt)` at `pydanticai.py:178`, which would otherwise happily serialise the pause into an
ordinary structured reply because it accepts any `BaseModel` (`model.py:157-158`).

### Persist

Two pieces: `to_jsonable_python(result.all_messages())` — which the adapter **already writes to
the session** at `pydanticai.py:173-174` — plus the `DeferredToolRequests` object itself
(`.approvals`, `.calls`, `.metadata`), so the resume side can rebuild `DeferredToolResults`
keyed by `tool_call_id`.

### Resume

```python
result = await agent.agent.run(content, message_history=history, deferred_tool_results=results)
```

The `message_history` reconstruction is **already written** — `pydanticai.py:166` builds it from
the stored session messages on every run. So resume is the existing call with one extra kwarg.

### Streaming

Best-supported of the four: `DeferredToolRequestsEvent` is emitted on the stream, and the
adapter already consumes `run_stream_events()` (`pydanticai.py:190+`). Mapping that event to an
AK pause event is a direct translation, no state reconstruction needed.

### Adapter-specific problems to solve

1. **`output_type` must include `DeferredToolRequests`.** This is a user-side agent-construction
   change, not something the adapter can do to an already-built agent — unless AK passes
   `output_type` at run time, which the Pydantic AI docs say overrides the constructor value.
   **Doing so would change the agent's typing on every AK run, including runs with no gated
   tools** — a decision with real consequences that must not be made silently.
2. **`requires_approval` has the same reachability problem as OpenAI's `needs_approval`** — it is
   declared at tool-definition time, which AK's `ToolBuilder` owns.
3. `deps=` is already used for `framework_context` (`pydanticai.py:169-171`), so the resume path
   must keep loading and storing it exactly as `run()` does, or a resumed turn silently drops the
   caller's context.

---

## Google ADK

**Verdict: workable, but the only one of the four with structural blockers in the current
adapter and unresolved upstream bugs.**

### Pause

The adapter must stop discarding events. `get_response()` (`adk.py:204-230`) keeps only
`is_final_response()` text; it needs to also inspect each event for:

- `event.long_running_tool_ids` intersecting a part's `function_call.id` — a
  `LongRunningFunctionTool` pause; and/or
- a `function_call` named `adk_request_confirmation` — an action-confirmation pause, carrying
  `hint` and `payload`.

Both require capturing the whole `FunctionCall` (id **and** name), because resume echoes both
back.

### Persist

The pending `FunctionCall`'s id and name, the confirmation hint/payload if present, and the
`invocation_id`. The conversation itself lives in the ADK session's event history, held by
`InMemorySessionService` inside `GoogleADKSession` (`adk.py:59-70`), which is stored under the
framework key and therefore pickled with the AK session. **Verified: that service pickles cleanly
both empty and while holding a live session** ([`verification.md`](verification.md)), so ADK pause
state is durable on any configured session backend rather than single-process only.

### Resume

```python
updated = pending_call_response.model_copy(deep=True)
updated.response = {'status': 'approved'}                     # or {'confirmed': True, 'payload': {...}}
runner.run_async(user_id=..., session_id=..., new_message=types.Content(
    parts=[types.Part(function_response=updated)], role='user'))
```

plus `invocation_id=` when the app is resumable.

### Adapter-specific problems to solve

1. **The `Runner` is built from a bare agent, not an `App`** (`adk.py:201`), so
   `ResumabilityConfig(is_resumable=True)` is unreachable. Enabling it means constructing
   `App(name=..., root_agent=agent.agent, resumability_config=...)` and building the `Runner`
   from that — a change to how every ADK run is set up, affecting agents that never pause.
2. **`create_session` is a one-shot no-op after the first call** (`adk.py:79-82`: `if
   self._session is None`), so resume reuses the same ADK session, which is what we want — but
   `_setup_session_context` also appends a state-delta event on every run (`adk.py:196-199`).
   Whether that extra event disturbs a resumed invocation is untested.
3. **Streaming pause: decide by test, do not declare it unsupported up front.** *(Revised.)* The
   earlier recommendation here — spend issue #606's "documents explicit incompatibility"
   allowance on ADK streaming — rested on upstream issues that turned out to be **closed** and
   against **ADK 1.x**, not the pinned 2.5.0; and on documentation that **does not exist**. See
   the survey's ADK caveats and `verification.md`. Two mechanisms in 2.5.0's source keep it
   risky (the two-event pause window ADK itself calls a known limitation, and the
   partial-vs-persisted id split), but neither has been observed failing. Test it in the ADK PR;
   support it if it works; if it does not, document AK's own finding with a repro rather than
   citing an upstream position that was never taken.
4. **ADK's own "tools may run more than once when resuming"** warning must reach AK's users.

---

## CrewAI — recommend explicit non-support

Not a scope cut for convenience; the mechanism genuinely does not intersect the adapter.

- `@human_feedback` decorates methods on a CrewAI **`Flow`**. AK wraps CrewAI **`Agent`s**
  (`crewai.py:544-550`) and builds a throwaway `Task` + `Crew` per run
  (`crewai.py:375-386`). There is no Flow to decorate.
- The other route, `Task(human_input=True)`, blocks on console `input()` — wrong inside a server
  process, and undocumented mechanically by CrewAI itself.
- The production-shaped webhook route is Enterprise/AMP only.
- Supporting it properly means teaching AK to wrap CrewAI Flows, which also imports a second
  persistence system (`SQLiteFlowPersistence`) that would sit alongside — and disagree with —
  AK's session store.

**Recommendation:** `supports_pause = False`; a `resume()` that raises a clear
`NotImplementedError` naming the reason; and a documented pointer to CrewAI Flows for users who
need it. This mirrors how the adapter already handles streaming (`crewai.py:412-423`) and
`framework_context` (`crewai.py:381-385`, warn-once and skip).

## smolagents — recommend explicit non-support

- The documented pattern is a `step_callbacks` hook on `PlanningStep` that either blocks on
  console input or interrupts, with resume by re-running `agent.run(task, reset=False)`.
- There is no serialisable pending-call record — nothing that says *what* was asked or *which*
  call resumes. AK would have to invent the pause payload, which is exactly the "never fake a
  guarantee" line.
- The adapter already persists `agent.memory.steps` to the session
  (`smolagents.py:98-125`), so a coarser "re-run with preserved memory" pause is *conceivable* —
  but it would be an AK-invented mechanism wearing a framework-native name, and it would not
  survive multiple replicas because the callback runs in-process.

**Recommendation:** same treatment as CrewAI — `supports_pause = False`, matching the existing
streaming stance (`smolagents.py:187-199`).

---

## Cross-cutting: the three problems this survey did not solve

1. **How a gated tool gets declared.** OpenAI (`needs_approval`), Pydantic AI
   (`requires_approval`), and ADK (`require_confirmation` / `LongRunningFunctionTool`) all
   declare the gate at tool-definition time, which is `ToolBuilder`'s territory
   (`core/tool.py`). Either AK grows a framework-agnostic way to mark a bound tool as
   requiring approval — which would be a genuinely valuable cross-framework feature — or HITL
   only works for users who hand AK framework-native tools. **LangGraph is the exception**: its
   gate is `interrupt()` inside a user node, entirely outside AK's tool layer.
2. **Whether resume re-runs the pre-hook chain.** A resume is not a new user turn: input
   guardrails and the multimodal pre-hook have no input to act on, and re-running them on a
   decision payload is at best wasted work. But post-hooks (output guardrails) clearly *should*
   run on the resumed reply.
3. **What a pause means for the response store and the queue pipeline.** A paused run returns a
   real, complete outcome — not an error and not a partial — so it should reach the client with
   its own status rather than a 200 that looks like an answer. The scheduling capability already
   set this precedent with its 202 (`chat_service.py:547-554`), but it derives the status from
   the *request* (`req.schedule is not None`), whereas a pause is only knowable from the *reply*.
