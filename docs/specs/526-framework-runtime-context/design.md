# #526: Pass a per-run framework context/state through the Session to every framework adapter

Give application code a framework-agnostic way to carry a **context/state object** across turns of a conversation: persist it in the `Session` under a reserved key, inject it into the underlying framework when the agent runs, and write the (possibly mutated) object back to the same key after the run. Each of the five framework adapters maps this one AK-level object onto its own native context/state mechanism.

## Motivation

- Every framework accepts caller-supplied context/state, but AK threads none of it through today — each runner sets up only the AK-internal `ToolContext` contextvar and never passes a native context object into the framework call:
  - OpenAI: `Runner.run(agent.agent, input_data, session=session_to_use)` — no `context=` argument (`ak-py/src/agentkernel/framework/openai/openai.py:183`).
  - LangGraph: `agent.agent.ainvoke(input={"messages": messages}, config=config)` — `config` only carries `thread_id`; no caller state merged in (`ak-py/src/agentkernel/framework/langgraph/langgraph.py:390`, config built at `:353`).
  - CrewAI: `crew.kickoff_async(inputs={})` — inputs are hard-coded empty (`ak-py/src/agentkernel/framework/crewai/crewai.py:378`).
  - Google ADK: session state is seeded only with the internal `ak_tool_context` id (`ak-py/src/agentkernel/framework/adk/adk.py:162`).
  - Smolagents: `agent.agent.run(prompt, reset=False)` — no `additional_args` (`ak-py/src/agentkernel/framework/smolagents/smolagents.py:157`).
- The `Session` already stores per-framework state under a framework-name key (`session.get(FRAMEWORK) or session.set(FRAMEWORK, ...)`) — e.g. `openai.py:95`, `langgraph.py:326`, `crewai.py:316`, so a caller-facing context key fits the existing key/value model on `Session` (`get`/`set`, `ak-py/src/agentkernel/core/base.py:124`, `:160`).
- Durable session keys already survive across turns: `Runtime.run()` calls `self.sessions().store(session)` after post-hooks (`ak-py/src/agentkernel/core/runtime.py:218`), and `store()` persists every non-volatile top-level key (`Session.get_all`, `base.py:135`). A new top-level key is persisted with no extra plumbing.
- Session values are serialized with `pickle` (`BinarySerde.dumps/loads`, `ak-py/src/agentkernel/core/session/serde.py:24`,`:36`), so any context object must be picklable — this constrains what a caller may put in it.
- Hooks can already read and mutate the session (`PreHook.on_run(session, ...)` / `PostHook.on_run(session, ...)`, `ak-py/src/agentkernel/core/hooks.py:21`,`:51`), but a hook **cannot** inject the object into the native framework call — only the runner, which owns the `Runner.run`/`ainvoke`/`kickoff_async` invocation, can. So injection must live in each runner.

## Requirements

### Core

- Reserve a **single** session key `framework_context` shared by all frameworks. Add it to the `Session.Keys` enum (`base.py:35`), alongside `v_cache`/`nv_cache`, rather than a bare module constant — same discoverability and one obvious home for the reserved name. *(Decision: open question 1.)*
  - **Absent key** (`session.get(...)` returns `None`) ⇒ inject nothing / framework default ⇒ **no behavior change** for existing apps.
  - A caller-set **empty dict `{}`** is treated as "present but empty": it is injected (a no-op for every framework) and round-tripped, so a caller can seed an empty context on turn 1 and have tools populate it. Only `None`/absent means "no context".
  - The value is a **`dict`**. *(Decision: open question 4.)*
- **Caller API surface**: no new surface — callers seed/read the context via the existing `session.set(...)` / `session.get(...)`, using `Session.Keys.FRAMEWORK_CONTEXT.value` as the key (the enum member is the canonical name; callers reference it rather than hardcoding the bare `"framework_context"` literal, avoiding string drift); inside a tool it is reachable via `ToolContext.get().session`. *(Decision: open question 2 — "no" extra surface.)*
- Provide the load/write-back plumbing once, in the base `Runner` (`base.py:192`), so each adapter only implements the native mapping:
  - `_load_framework_context(session) -> dict | None` — read the reserved key. **Returns a deep copy**, not the live stored object (see "Load semantics" below).
  - `_store_framework_context(session, ctx) -> None` — merge `ctx` over the loaded context per the merge rule and write it back to the same key.
- Runners call load before invoking the framework and write-back after the native call completes, for both `run()` and `stream()`. Placement is per-adapter, not a uniform `try`/`finally` shape: OpenAI/LangGraph/CrewAI/smolagents wrap the call in `try/except … finally: context.reset()`, but **ADK's `run()` uses `with ctx:` (`adk.py:213`) rather than a `finally: context.reset()`** — it has a `try/except` (`adk.py:206,224`) but no `finally`, so its write-back goes after the `with ctx:` block, inside the `try`. Each adapter places the `_load_/_store_` calls around its own native invocation; do not assume a shared try-body across all five.

### Load semantics — return a deep copy

- `_load_framework_context` returns a **deep copy** of the stored dict, and write-back stores the merge result. Its main purpose is **crash-isolation**: OpenAI tools mutate the injected object **in place** (they write through `RunContextWrapper.context`), so if load handed out the live stored reference, the session key would already reflect partial tool mutations *before* write-back — and a mid-run crash (write-back skipped, see "Write-back") would leave the stored context half-mutated. Copying on load keeps the stored object untouched until a successful write-back replaces it wholesale.
  - Note: for OpenAI specifically the "incoming" copy and the "post-run" object are the **same reference** (tools mutate the copy), so the shallow-merge there is effectively identity. The merge rule does real work only for frameworks whose write-back source is a *different* object than the injected one — smolagents `agent.state`, ADK session `state`, LangGraph `result` — where untouched caller keys must be preserved.

### Write-back — always reflect the latest context

- After the run, the key is **updated with the latest context** — any mutations the framework surfaced during the run, shallow-merged over the incoming (copied) context per the merge rule in the per-framework table. *(Decision: open question 3.)*
- **On framework error, do not write back.** *(Decision.)* Every runner catches its own exceptions and returns an error reply (`openai.py:191`, `langgraph.py:399`, `crewai.py:397`, `smolagents.py:167`, `adk.py:224`), so `store()` still runs afterward (`runtime.py:218`) and persists the session — but the write-back must sit **after a successful native call, inside the `try` and before the `except`**, so a crashed or partial run is skipped and the **previously stored context is left intact** (the deep copy loaded this turn is simply never written back). A turn's context update is therefore atomic: it either fully reflects a completed run or is unchanged.
- Fidelity is per-framework (see the table), not uniform: OpenAI round-trips fully; smolagents/ADK round-trip the caller's keys after filtering internal entries; LangGraph round-trips only keys its state schema declares; CrewAI does not support it — a set `framework_context` is refused with a warning and never injected or written back.
- **Merge rule**: the framework's post-run state is **shallow-merged over** the incoming context — top-level keys the framework touched win (last-write-wins), keys the caller seeded but the framework never touched are preserved, and nested structures are replaced wholesale by the winning side (no deep/recursive merge). *(Decision.)*
- Never overwrite the key with an empty/`None` value when no context was present or produced (a caller-set `{}` is "present" and is preserved — see Core).

### Per-framework mapping

The `framework_context` dict is **merged into** the native mechanism on input (added to, not replacing, existing native state) and the produced state is read back on output. **The five frameworks differ in how faithfully they can round-trip a caller dict** — the mapping is graded honestly below rather than presented as uniform, because the write-back fidelity is not the same everywhere and callers need to know where mutations actually survive.

| Framework | Fidelity | Inject on input (merge) | Write-back source |
|---|---|---|---|
| OpenAI | **Full round-trip** | `Runner.run(..., context=ctx)` / `Runner.run_streamed(..., context=ctx)` — tools read/write via `RunContextWrapper.context` (`openai.py:183,214`) | the same object, mutated in place by tools |
| Smolagents | **Round-trips (filtered)** | `agent.run(prompt, additional_args=ctx, reset=False)` (`smolagents.py:157`) | `agent.state` read after the run, **restricted to the keys the caller seeded** — `agent.state` also holds framework-internal entries that must not leak into `framework_context` |
| Google ADK | **Round-trips (filtered)** | merge into the ADK session `state` delta alongside `ak_tool_context` (`adk.py:162`) | ADK session `state` read after the run, **with the AK-internal `ak_tool_context` key stripped** (see ADK note) |
| LangGraph | **Round-trips only for declared state channels** | **spread** the dict's top-level keys into the `ainvoke`/`astream_events` `input` alongside `messages` — `input={**framework_context, "messages": messages}` — `messages` written last (`langgraph.py:391,427`). The keys sit at the **top level** of the input state (so they map onto the graph's state channels), **not** nested under a `framework_context` key, and never replace `messages` | keys read back only if the graph's state schema declares them as channels (see LangGraph note) |
| CrewAI | **Unsupported — warn and skip** | not injected; a set `framework_context` is refused with a warning (see CrewAI note) | none; the stored key is left untouched |

On write-back the produced state is shallow-merged over the incoming (copied) context per the **Merge rule** above (framework value wins per touched top-level key; untouched caller keys preserved; no deep merge).

- **CrewAI note (unsupported — warn and skip)**: CrewAI's `kickoff(inputs=...)` are **template-interpolation variables**, not a context/state object — they `.format()`-substitute `{placeholder}` tokens in the task `description`/`expected_output` and the agent `role`/`goal`/`backstory`. Today `inputs={}` is passed (`crewai.py:378`), so interpolation is effectively skipped; passing a non-empty `inputs=ctx` would **turn interpolation on** and raise `KeyError` on any literal `{`/`}` in the (user-derived) task description built by `_describe(...)` (`crewai.py:305`). CrewAI therefore exposes **no safe caller-state slot**. **Behavior:** when a session carries a non-empty `framework_context`, the CrewAI runner does **not** inject it and logs a **single warning** (once per run) — e.g. `"framework_context is set but CrewAI does not support per-run caller context/state; ignoring it."` — via the runner's `self._log.warning(...)`. `kickoff_async(inputs={})` stays as-is, and the stored key is left untouched (no write-back). This makes the limitation explicit at runtime rather than silently dropping the context. (A tool that still needs the dict can reach it via `ToolContext.get().session`.)
- **ADK note**: `GoogleADKSession` uses an `InMemorySessionService` (`adk.py:53`), so ADK's native state is **not** part of the pickled AK session — write-back is what gives the context cross-turn durability (via AK's `framework_context` key), not ADK itself. The read-back scope is the state accumulated by the run; the runner seeds `{"ak_tool_context": ctx.id}` with a **fresh id every turn** (`adk.py:162`), so write-back **must strip `ak_tool_context`** (and any future AK-internal keys) before merging — otherwise the caller's dict accumulates a stale internal id.
- **LangGraph note**: this `framework_context` is distinct from the graph's own checkpointed state. LangGraph already persists its conversational state via a pickle-serializable `CheckPointer` held in `LangGraphSession` under the `"langgraph"` key (`langgraph.py:264/273`, wired at `:355`). Merged caller keys **only round-trip if the graph's state schema declares them as channels** — a prebuilt `create_react_agent` uses `AgentState` (`messages`, `remaining_steps`, `structured_response`), which silently drops unknown keys, so nothing extra comes back off `result`. Read-back is meaningful only for custom graphs whose state schema includes the caller's keys; for the prebuilt case the value is the uniform cross-framework API, not new persistence.
- **Smolagents note (new keys don't round-trip)**: write-back reads `agent.state` after the run but **restricts it to the keys the caller seeded** — `agent.state` also holds framework-internal entries with no clean prefix to filter on, so the only safe read-back scope is "keys already present in the incoming context". Consequence: a tool that **mutates a seeded key** round-trips, but a tool that **adds a brand-new key** to the context has it **silently dropped** on smolagents (that same new key survives on OpenAI — full round-trip — and on ADK, which strips only AK-internal keys). This is a genuine cross-framework divergence: tool authors who want a context write to be portable across all frameworks must **pre-seed every key they intend to write** into `framework_context` before the run.

### Behavior / compatibility

- Optional throughout: existing sessions and apps that never set the key are unaffected.
- Persistence: the key is a normal durable session key — persisted by `store()` and reloaded on the next turn (already covered by `Runtime.run`/`SessionStore`).
- Streaming parity: `stream()` performs the same load (before the token loop) and write-back (once, after it) as `run()` — the per-token yielding is unchanged. **Write-back happens only when the stream *completes normally*, not on every stop.** *(Decision.)* A stream can end three ways, and only one writes back:
  - **Drained normally** (all tokens yielded, loop exits) ⇒ read back the produced state and merge into the session key.
  - **Client disconnected mid-stream** (`GeneratorExit` raised at a `yield`) ⇒ **no write-back**; the previously stored context is left intact.
  - **Framework raised mid-stream** ⇒ **no write-back** (same rule as the `run()` error path above).
  - Mechanically: place the write-back **after the `async for` loop but still inside the `try`**, so a disconnect or exception unwinds before reaching it and the write-back is naturally skipped — do **not** move it into a `finally` (that would persist a partial, half-produced context). This keeps streaming atomic and consistent with `run()`: a turn's context either fully reflects a completed stream or is unchanged. Consequence to state plainly: if a user disconnects after most of a long stream, that turn's context mutations are **discarded**, not partially saved — last-known-good is preferred over partial state.
- **The read-back source differs on the streaming path** and must be specified per adapter — the streaming APIs do not all hand back a state object the way `run()` does. The read-back read itself must also sit inside the guarded region, so a failed read skips write-back rather than persisting a partial merge:
  - OpenAI: `Runner.run_streamed(..., context=ctx)` — same in-place-mutation model as `run()`, the injected `ctx` object is the source; no extra fetch.
  - LangGraph: `astream_events` yields events, not a final `result` dict (`langgraph.py:426`); read state back via an explicit `agent.agent.aget_state(config)` after the stream completes, then merge.
  - ADK: read the ADK session `state` after the event stream drains (same source as `run()`), with `ak_tool_context` stripped.
  - smolagents/CrewAI: no native token streaming (`stream()` raises `NotImplementedError`), so no streaming write-back applies.

### Serialization

- `framework_context` must be picklable — sessions are serialized with `pickle` via `BinarySerde` (`serde.py:24/36`), so a non-picklable value would otherwise crash the whole session `store()`.
- **Policy (Decision):** fail fast. At write-back, run a targeted picklability check on the `framework_context` value alone and, on failure, raise a descriptive error naming the key and the offending type. This surfaces an actionable message during development instead of an opaque store-level pickle error, and never silently drops the context between turns.
- **Scope of the check — diagnostic, not preventive:** on frameworks where tools mutate the injected object in place (OpenAI), the non-picklable value is already present in the session before write-back runs, so the check improves the *error message* but cannot prevent the bad state from having been produced. The check runs on the merge result before `store()` either way, so the descriptive error still fires ahead of the opaque `store()` pickle failure.

## Non-goals

- Not changing how each framework stores its own internal state (the framework-name keys, and LangGraph's `CheckPointer`, stay as they are).
- Not injecting context into agent-to-agent / sub-agent calls within a workflow — hooks and this mechanism cover only the top-level run (same limitation noted in `hooks.py:15`).
- Not defining a schema/validation model for the context contents (free-form `dict`).

## Open questions

- None outstanding — all prior open questions are resolved above.
