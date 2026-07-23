# #526: Pass a per-run framework context/state through the Session to every framework adapter — Implementation Spec

This spec details how the reviewed `design.md` is built. A single reserved session key, `framework_context`, carries a picklable `dict` across turns: the base `Runner` provides load / write-back plumbing, and each of the five framework adapters maps that one AK-level dict onto its native context/state mechanism (or, for CrewAI, declines it with a warning). No new caller API surface is added — callers use the existing `session.get(...)` / `session.set(...)` with `Session.Keys.FRAMEWORK_CONTEXT.value`. `design.md` in this directory is the requirements source; every requirement there is traced to a section below.

## Design

### 1. `Session.Keys` — reserve the key (`core/base.py`)

Add one enum member alongside the existing cache keys (`base.py:35-41`):

```python
class Keys(Enum):
    VOLATILE_CACHE = "v_cache"
    NON_VOLATILE_CACHE = "nv_cache"
    FRAMEWORK_CONTEXT = "framework_context"
```

Rules:
1. `framework_context` is a **normal durable top-level key** — no change to `Session.get_all()` (`base.py:135-144`) is needed. `get_all()` treats every key except `v_cache` as durable, so `store()` (`runtime.py:218`) already persists and reloads it. It is **not** pre-initialized in `Session.__init__` (unlike the two caches at `base.py:65-66`): an unset key must read back as `None` so "absent ⇒ no injection ⇒ no behaviour change" holds.
2. Callers reference `Session.Keys.FRAMEWORK_CONTEXT.value` (the canonical name) rather than the bare `"framework_context"` literal.

### 2. Base `Runner` plumbing (`core/base.py`, class `Runner` at `base.py:192`)

Provide the load / merge / write-back logic once so each adapter only supplies the native mapping. Add `import copy` and `import pickle` to `base.py`.

```python
class Runner(ABC):
    ...
    def _load_framework_context(self, session: Session) -> dict | None:
        """Return a DEEP COPY of the stored framework_context, or None if the key is absent.
        A deep copy isolates the stored object from in-run mutation (crash-isolation):
        the stored key is untouched until a successful write-back replaces it wholesale."""
        if session is None:
            return None
        stored = session.get(Session.Keys.FRAMEWORK_CONTEXT.value)
        if stored is None:
            return None            # absent  → caller injects nothing / framework default
        return copy.deepcopy(stored)  # present (incl. {}) → injected and round-tripped

    def _store_framework_context(
        self, session: Session, incoming: dict | None, produced: Mapping[str, Any] | None
    ) -> None:
        """Shallow-merge `produced` over `incoming` and write the result back to the key.
        `incoming` is the deep copy returned by _load_framework_context this turn.
        No-op when the key was absent this turn (incoming is None) — the previously
        stored context is left intact."""
        if session is None or incoming is None:
            return                         # absent key → never overwrite
        merged = dict(incoming)            # caller-seeded keys the framework never touched are preserved
        if produced:
            merged.update(produced)        # framework-touched top-level keys win (last-write-wins, shallow)
        self._ensure_framework_context_picklable(session, merged)
        session.set(Session.Keys.FRAMEWORK_CONTEXT.value, merged)

    @staticmethod
    def _ensure_framework_context_picklable(session: Session, ctx: Mapping[str, Any]) -> None:
        """Fail fast with an actionable message if the merged context can't be pickled,
        instead of the opaque store()-level pickle failure that would abort the whole
        session store()."""
        try:
            pickle.dumps(ctx)
        except Exception as exc:
            offender = next(
                (f"{k!r} ({type(v).__name__})" for k, v in ctx.items()
                 if _not_picklable(v)),
                "<unknown key>",
            )
            raise TypeError(
                f"Session '{session.id}' framework_context is not picklable; "
                f"offending entry: {offender}. framework_context values must be "
                f"pickle-serializable so the session can be persisted."
            ) from exc
```

Governing rules (numbered so review can check each):

1. **Deep copy on load.** `_load_framework_context` never hands out the live stored object. For OpenAI, tools mutate the injected object in place; without the copy a mid-run crash would leave the stored key half-mutated. Copying keeps the turn atomic.
2. **Merge is shallow, produced-over-incoming.** Top-level keys the framework touched win; untouched caller keys survive; nested structures are replaced wholesale (no recursive merge). This lives in the base helper because the merge *rule* is uniform across frameworks — only the *`produced` extraction* differs per adapter (see §3).
3. **Absent vs present-empty.** `incoming is None` (key absent) ⇒ never write. `incoming == {}` (caller-set empty) ⇒ present ⇒ write back the merge (a no-op-shaped `{}` or whatever tools produced). This is why the key must not be pre-initialized (rule 1 of §1).
4. **Picklability is a diagnostic, not preventive, check.** It runs on the merge result *before* `session.set(...)` so it fires ahead of the `store()`-level pickle error. On OpenAI the offending value already exists in the injected copy the tool mutated; the check cannot un-create it, but it converts an opaque store crash into a named error and leaves the previously stored context intact.

> **Clarification vs design.md** (behaviour unchanged, surfaced per the write-spec process): `design.md` sketches `_store_framework_context(session, ctx)` and describes it as "merge `ctx` over the loaded context". Because the base `Runner` is stateless across a run, the loaded context can't be recovered inside the helper — so the signature takes **both** operands explicitly: `incoming` (the deep copy from `_load`) and `produced` (the framework's post-run delta). The merge semantics are exactly as `design.md` specifies. `_not_picklable(v)` is a tiny module-level helper doing a per-value `pickle.dumps` in a `try/except` to name the offender.

### 3. Per-adapter injection and write-back

Each runner: (a) calls `_load_framework_context(session)` before the native call; (b) injects the returned `incoming` (when not `None`) via its native mechanism; (c) after a **successful** native call, extracts `produced` and calls `_store_framework_context(session, incoming, produced)` **inside the `try`, before the `except`**, so a crashed/partial run skips write-back. Placement is per-adapter (not a uniform shape) because the try/except/finally structures differ.

| Framework | `incoming` injection | `produced` extraction (write-back source) |
|---|---|---|
| OpenAI | `Runner.run(..., context=incoming)` / `Runner.run_streamed(..., context=incoming)` | `produced = incoming` (tools mutate it in place; merge is identity) |
| Smolagents | `agent.run(prompt, additional_args=incoming, reset=False)` — only when `incoming is not None` | `agent.state`, **filtered to `incoming`'s keys**: `{k: agent.state[k] for k in incoming if k in agent.state}` |
| Google ADK | seed state delta: `{"ak_tool_context": ctx.id, **(incoming or {})}` | ADK session `state` read back, **`ak_tool_context` (and any AK-internal key) stripped** — **not** restricted to `incoming`'s keys, so tool-added keys round-trip (see note) |
| LangGraph | spread top-level keys into input: `input={"messages": messages, **(incoming or {})}` | `{k: result[k] for k in incoming if k in result}` (only keys the graph's state schema declared as channels come back) |
| CrewAI | **not injected**; `kickoff_async(inputs={})` unchanged | none — write-back skipped entirely (warn once when a non-empty context is set) |

#### 3.1 OpenAI (`framework/openai/openai.py`)

- `run()` (`openai.py:166`): after `_get_run_input(...)`, load `incoming = self._load_framework_context(session)`; pass `context=incoming` to `Runner.run(agent.agent, input_data, session=session_to_use, context=incoming)` (`:183`). After the call succeeds and before returning, `self._store_framework_context(session, incoming, incoming)`. The existing `try/except Exception/finally: context.reset()` shape (`:175-195`) is kept; the load sits at the top of the `try`, the store just before `return` inside the `try`.
- `stream()` (`openai.py:197`): load before `Runner.run_streamed(..., context=incoming)` (`:214`); place `_store_framework_context(session, incoming, incoming)` **after the `async for` loop, still inside the `try`** (`:216-219`) so `GeneratorExit` (client disconnect) or an exception unwinds before it. Do **not** move it into the `finally`.
- Injecting `context=None` when the key is absent is a no-op and matches today's implicit behaviour (no `context=` passed today).

#### 3.2 Smolagents (`framework/smolagents/smolagents.py`)

- `run()` (`smolagents.py:126`): load `incoming` after `_hydrate_memory` (`:154`). Build the thread call so `additional_args` is passed **only when `incoming is not None`** — preserving today's exact `asyncio.to_thread(agent.agent.run, prompt, reset=False)` call when no context is set (so the existing test assertion at `test_smolagents_runner.py:62` still holds for the no-context path):
  ```python
  run_kwargs = {"reset": False}
  if incoming is not None:
      run_kwargs["additional_args"] = incoming
  reply = await asyncio.to_thread(agent.agent.run, prompt, **run_kwargs)
  ```
- After the run and `_sync_memory`, extract from `agent.agent.state` restricted to `incoming`'s keys and write back:
  ```python
  produced = None
  if incoming is not None and hasattr(agent.agent, "state") and isinstance(agent.agent.state, dict):
      produced = {k: agent.agent.state[k] for k in incoming if k in agent.agent.state}
  self._store_framework_context(session, incoming, produced)
  ```
  This is inside the `try` before `return`, so the existing `except`/`finally: context.reset()` (`:167-171`) is unchanged.
- Consequence (already stated in `design.md`): a tool that adds a **brand-new** key is silently dropped on smolagents because the filter is `incoming`'s keys only; a tool that mutates a **pre-seeded** key round-trips. `stream()` raises `NotImplementedError` (`:173-179`) — no streaming write-back.
- `agent.state` / `additional_args` are the smolagents `MultiStepAgent.run` surface; guarded by `hasattr`/`isinstance` so a version without `state` degrades to "no round-trip" rather than raising.

#### 3.3 Google ADK (`framework/adk/adk.py`)

ADK's native state lives in an `InMemorySessionService` (`adk.py:53`) and is **not** part of the pickled AK session, so write-back is what gives cross-turn durability.

- `_setup_session_context()` (`adk.py:146`) currently seeds `{"ak_tool_context": ctx.id}` (`:162`). Change it to accept the injected context and seed it alongside:
  ```python
  async def _setup_session_context(self, agent, session, requests, injected: dict | None):
      ...
      state = {"ak_tool_context": ctx.id}
      if injected:
          state.update(injected)
      await adk_session.update_session_state(ctx.id, agent.name, state)
      return user_id, runner, ctx, adk_session
  ```
  Return `adk_session` too, so the caller can read state back without re-fetching.
- Add a read-back helper on `GoogleADKSession` that returns the current state with AK-internal keys stripped:
  ```python
  async def get_state(self) -> dict:
      if self._session is None:
          return {}
      refreshed = await self._session_service.get_session(
          app_name="AgentKernel", user_id="AgentKernel", session_id=self._session.id
      )
      state = dict(getattr(refreshed, "state", {}) or {})
      state.pop("ak_tool_context", None)   # strip AK-internal key(s) — fresh id every turn
      return state
  ```
- `run()` (`adk.py:198`): load `incoming` at the top of the `try` (`:206`); pass it into `_setup_session_context(...)`. After the `with ctx:` block (`:213-214`) and before returning, when `incoming` is not `None` read `produced = await adk_session.get_state()` — the full accumulated state with AK-internal keys already stripped by `get_state()`, **not** filtered to `incoming`'s keys — and `self._store_framework_context(session, incoming, produced)`. Because `produced` is the whole (stripped) state, keys a tool **added** during the run round-trip (they appear in `produced` and win the shallow merge), matching `design.md:60,62`; this is the deliberate divergence from smolagents (§3.2), where the read-back is restricted to seeded keys. ADK's `run()` has a `try/except` (`:206,224`) but **no `finally`** — the write-back goes at the end of the `try`, before the `except`.
- `stream()` (`adk.py:227`): load before `_setup_session_context`; after the `async for` loop inside the `with ctx:` block completes normally, read state and write back — inside the guarded region, so a disconnect/exception skips it.

#### 3.4 LangGraph (`framework/langgraph/langgraph.py`)

`framework_context` is distinct from the graph's own checkpointed state (`CheckPointer`, `langgraph.py:273`, wired at `:355`). Caller keys round-trip **only** when the graph's state schema declares them as channels (a prebuilt `create_react_agent` uses `AgentState` and silently drops unknown keys).

- `run()` (`langgraph.py:366`): load `incoming` after `_prepare_session_and_messages(...)` (`:388`). Spread its top-level keys into the input at `:390-393`:
  ```python
  input_state = {"messages": messages}
  if incoming:
      input_state.update(incoming)       # top-level channels, never replacing `messages`
  result = await agent.agent.ainvoke(input=input_state, config=config)
  ```
  After success, `produced = {k: result[k] for k in incoming if k in result}` (when `incoming` not `None`), then `_store_framework_context(session, incoming, produced)` — inside the existing `try` before the `except` (`:399`); the `finally: context.reset()` (`:401-403`) is unchanged.
- `stream()` (`langgraph.py:405`): spread `incoming` into the `astream_events` input the same way (`:426-430`). `astream_events` yields events, not a final state dict, so read state back with `state = await agent.agent.aget_state(config)` **after** the `async for` loop, inside the `try`; `produced = {k: state.values[k] for k in incoming if k in state.values}`, then write back. Skipped on disconnect/exception by placement.

#### 3.5 CrewAI (`framework/crewai/crewai.py`) — unsupported, warn and skip

CrewAI's `kickoff(inputs=...)` are `.format()` template-interpolation variables, not a state object; a non-empty `inputs` would turn interpolation on and raise `KeyError` on literal braces in the `_describe(...)` task description (`crewai.py:294-305`). There is no safe caller-state slot.

- In `run()` (`crewai.py:324`), after building the prompt and before `kickoff_async` (`:378`), check the key **once per run** and warn, without loading/injecting:
  ```python
  if session is not None and session.get(Session.Keys.FRAMEWORK_CONTEXT.value):
      self._log.warning(
          "framework_context is set but CrewAI does not support per-run caller "
          "context/state; ignoring it."
      )
  ```
  `session.get(...)` truthiness means a caller-set `{}` (falsy) does **not** warn; only a non-empty dict does.
- `kickoff_async(inputs={})` stays as-is. No `_load_/_store_framework_context` calls — the stored key is left untouched (a set `{}` is preserved; a non-empty dict is preserved unchanged). Tools that need the dict still reach it via `ToolContext.get().session`.
- `stream()` raises `NotImplementedError` (`:403-409`) — no streaming path.

### Consumer changes

- **`core/base.py`**: add `FRAMEWORK_CONTEXT` enum member; add `_load_framework_context`, `_store_framework_context`, `_ensure_framework_context_picklable` to `Runner`; add `import copy`, `import pickle`, and `_not_picklable` helper. `Session`, `Agent`, `Runtime` classes unchanged.
- **`framework/openai/openai.py`**: `OpenAIRunner.run` / `.stream` inject `context=` and write back. `OpenAIAgent`/`OpenAIModule`/`OpenAIToolBuilder` unchanged.
- **`framework/smolagents/smolagents.py`**: `SmolagentsRunner.run` injects `additional_args=` (conditionally) and writes back filtered `agent.state`. Everything else unchanged.
- **`framework/adk/adk.py`**: `GoogleADKRunner._setup_session_context` gains an `injected` param and returns `adk_session`; `GoogleADKSession` gains `get_state()`; `run`/`stream` load, seed, and write back. `get_response` signature unchanged.
- **`framework/langgraph/langgraph.py`**: `LangGraphRunner.run`/`.stream` spread `incoming` into the input state and write back declared channels. `_prepare_session_and_messages` unchanged.
- **`framework/crewai/crewai.py`**: `CrewAIRunner.run` adds a one-shot warning; no injection, no write-back.
- **No changes** to `core/runtime.py`, `core/hooks.py`, `core/session/*`, guardrails, multimodal, sandbox, deployment, or API layers — the key rides the existing `store()`/reload path.

### Config changes

**None.** `framework_context` is a runtime session value, not configuration — no new `AKConfig` field, no YAML block, no `AK_*` env var. Existing config files and env vars are unaffected. This matches `design.md` ("no new surface").

### Behavioural changes

Each is intentional and justified:

1. **OpenAI now passes `context=` to `Runner.run`/`run_streamed`.** Previously no context object was passed (`openai.py:183`). When the key is absent, `context=None` is passed — functionally identical to today. Justified: this is the feature.
2. **Smolagents passes `additional_args=` only when the key is present.** When absent, the call is byte-for-byte today's `asyncio.to_thread(agent.agent.run, prompt, reset=False)`. Justified: preserves the no-context path exactly and its existing test.
3. **ADK seeds caller keys into the state delta alongside `ak_tool_context`, and now reads state back after the run.** Previously only `ak_tool_context` was seeded and state was never read back. `ak_tool_context` is stripped on read-back. Justified: ADK's native state isn't pickled, so write-back is the only durability path.
4. **LangGraph spreads caller keys into the `ainvoke`/`astream_events` input.** Previously `input={"messages": messages}` only. Keys sit at the top level (state channels), never replacing `messages`. Unknown keys are dropped by prebuilt agents (no error). Justified: uniform cross-framework API; real round-trip for custom graphs.
5. **CrewAI logs a single warning when a non-empty `framework_context` is set.** Previously nothing was logged. Justified: makes the unsupported-status explicit at runtime rather than silently dropping.
6. **A new durable session key `framework_context` is persisted and reloaded** for every framework once a caller sets it. Justified: cross-turn carry is the feature; absent key ⇒ nothing persisted ⇒ no change for existing sessions.
7. **Write-back is atomic per turn.** On framework error or mid-stream disconnect (`GeneratorExit`) the previously stored context is left intact (write-back is skipped by placement inside the `try`, after the native call/loop, before `except`, never in `finally`).

**Non-changes** (fixed by this spec):
- No change to how each framework stores its own internal state (the framework-name keys, LangGraph's `CheckPointer`).
- No change to `Runner.run`/`Runner.stream` abstract signatures, `PreHook`/`PostHook`, or `Runtime.run`/`Runtime.stream`.
- No injection into agent-to-agent / sub-agent calls (same limitation as `hooks.py:15`).
- No schema/validation on context contents (free-form `dict`).
- `AgentReply`/`AgentRequest` models, public exports, and the caller API are unchanged.

## Error handling

- **Framework raises during the native call.** Each runner's existing `except Exception` returns a user-facing error reply (`openai.py:191`, `langgraph.py:399`, `crewai.py:397`, `smolagents.py:167`, `adk.py:224`). Because write-back sits before the `except`, it is skipped — the previously stored context is untouched. `store()` still runs (`runtime.py:218`) and persists the rest of the session.
- **Client disconnects mid-stream** (`GeneratorExit` at a `yield`) or **framework raises mid-stream.** Write-back is after the `async for` loop but inside the `try`, so it never runs — last-known-good context is kept, partial state is discarded.
- **Non-picklable context.** `_ensure_framework_context_picklable` raises a `TypeError` naming the session id and the offending key/type before `session.set(...)`. Raised inside the runner's `try`, it is caught by `except Exception` and surfaced through `user_facing_error_message` (unknown category ⇒ `"Error: <message>"`, `error_util.py:69-71`), so the actionable text reaches the caller/logs instead of an opaque `store()` pickle crash aborting the whole session store. The stored context is left intact.
- **`session is None`** (runner invoked without a session, e.g. some unit paths): `_load_framework_context` returns `None`, `_store_framework_context` no-ops — no injection, no write-back, no error.
- **Absent optional attributes** (`agent.state` on an older smolagents; ADK `get_session` returning no `state`): guarded with `hasattr`/`isinstance`/`getattr(..., {})`; degrade to "no round-trip", never raise.

## Testing

Run: `cd ak-py && uv run pytest`. New/changed tests follow existing patterns (`@pytest.mark.asyncio`, `MagicMock`/`AsyncMock`, `patch` at the module import site, `Session("id")` fixtures).

### New test file — `ak-py/tests/test_framework_context.py`

Base-`Runner` plumbing, framework-agnostic (uses `DummyRunner`-style subclass):
- **Absent key ⇒ no injection, no write-back**: `_load_framework_context` returns `None`; after `_store_framework_context(session, None, {"a": 1})` the key stays absent.
- **Deep-copy isolation**: seed `{"a": {"n": 1}}`, mutate the object returned by `_load_framework_context`, assert the stored object is unchanged.
- **Present-empty `{}` is preserved**: `_store_framework_context(session, {}, None)` writes `{}` back (not `None`).
- **Shallow merge / last-write-wins**: `incoming={"a": 1, "b": 2}`, `produced={"b": 9, "c": 3}` ⇒ stored `{"a": 1, "b": 9, "c": 3}`; nested dict replaced wholesale, not deep-merged.
- **Round-trip across turns**: `session.set(FRAMEWORK_CONTEXT, {"count": 0})`, run twice through a dummy runner that increments and writes back via the helpers, assert persistence.
- **Picklability failure**: merged context containing a `lambda`/open socket ⇒ `TypeError` naming the offending key/type; assert `session.set` was not called for the key (previous value intact).

### Changed / added runner tests

- **`ak-py/tests/test_openai_runner.py`**: add cases asserting (a) `MockRunner.run` is called with `context=<the loaded dict>` when the session has `framework_context`; (b) a tool-style in-place mutation of the injected context is written back to the session key after `run()`; (c) on `MockRunner.run` raising, the pre-existing `framework_context` is unchanged. Existing error/structured-output cases unchanged (they pass `context=None`).
- **`ak-py/tests/test_smolagents_runner.py`**: the existing assertion `mock_to_thread.assert_called_once_with(mock_agent.agent.run, "Hello smolagents", reset=False)` (`:62`) is the **no-context** path — keep it, and set no `framework_context`. Add a **with-context** case: seed the key, give `mock_agent.agent.state` a dict, assert `to_thread` is called with `additional_args=<incoming>` and that only seeded keys are written back (a brand-new state key is dropped).
- **`ak-py/tests/test_adk_runner.py`**: `_run_with_response` mocks `_setup_session_context` to a 3-tuple (`:25`) — update to the new 4-tuple `("user", runner_mock, ctx_mock, adk_session_mock)` and give `adk_session_mock.get_state` an `AsyncMock`. Add cases: seeded context is passed into `_setup_session_context`; the `get_state` result minus `ak_tool_context` is written back in full — a seeded key mutated by a tool round-trips **and** a brand-new key a tool added round-trips (asserting the ADK-vs-smolagents divergence); error path leaves the key intact.
- **`ak-py/tests/test_langgraph_runner.py`**: `_mock_agent` (`:16`) — add `agent.agent.aget_state` for the stream case. Add cases: `ainvoke` receives `input` containing the spread caller keys plus `messages`; keys present in `result` round-trip, absent ones are dropped; `messages` is never overwritten.
- **`ak-py/tests/test_crewai_runner.py`**: add a case asserting that setting a non-empty `framework_context` logs exactly one warning (via `caplog` on `ak.crewai.runner`) and that `kickoff_async` is still called with `inputs={}`; and that a caller-set `{}` logs nothing and is preserved.

### Streaming coverage

Add streaming write-back cases for OpenAI and LangGraph (and ADK) in the respective runner test files (or `test_framework_context.py`): normal drain writes back; a `GeneratorExit` raised at the consumer (simulating disconnect) leaves the stored context intact.

## Documentation updates

- **`docs/docs/core-concepts/session.md`** — under "How Sessions Work" / "Session Data Storage" (`session.md:358-399`), add a "Framework context / per-run state" subsection: what `framework_context` is, how to seed/read it via `session.set(Session.Keys.FRAMEWORK_CONTEXT.value, {...})` and from a tool via `ToolContext.get().session`, the picklable-`dict` constraint, and the atomic write-back-on-success rule.
- **`docs/docs/core-concepts/runner.md`** — note that runners inject this context into the native framework call and write the produced state back, with the per-framework fidelity table (full / filtered / declared-channels-only / unsupported).
- **`docs/docs/frameworks/*.md`** — add a short "Per-run context/state" note to `openai.md`, `smolagents.md`, `google-adk.md`, `langgraph.md`, and `crewai.md`, each stating that framework's fidelity: OpenAI full round-trip; ADK round-trips all keys except AK-internal ones (so tool-added keys survive); smolagents round-trips filtered to pre-seeded keys (new keys dropped); LangGraph only for declared state channels; **CrewAI unsupported (warn and skip)** with the `ToolContext` fallback.
- **`docs/docs/frameworks/multi-framework.md`** — call out the cross-framework divergence: to write portably, pre-seed every key you intend to write; new keys survive only on OpenAI/ADK, not smolagents/LangGraph-prebuilt/CrewAI.
- **Dev skills** — `.agents/skills/ak-dev-architecture/SKILL.md` (Session key list / Runner responsibilities) mentions the reserved `framework_context` key and the load/write-back responsibility; `.agents/skills/ak-dev-new-framework-integration/SKILL.md` gains a step: a new adapter's `run`/`stream` must call `_load_framework_context`/`_store_framework_context` and declare its round-trip fidelity. Confirm via the `ak-dev-sync-docs-from-branch` / `ak-dev-sync-skills-from-branch` flows before merge.
- **No update needed**: deployment READMEs, example projects (unless an example is added to demonstrate the feature — optional), and config docs (no config surface).

## Self-review — requirements traceability

Every `design.md` requirement maps to a section: reserved single key → §1; no new caller surface → §1 rule 2 + Config changes; base load/write-back helpers → §2; deep-copy load semantics → §2 rule 1; write-back-on-success-only / atomicity → §3 (per-adapter placement) + Error handling; merge rule → §2 rule 2; per-framework mapping table + notes → §3.1–3.5; streaming parity and per-adapter read-back source → §3.1/§3.3/§3.4 stream paragraphs; serialization fail-fast → §2 rule 4 + Error handling; non-goals preserved → Behavioural changes / Non-changes.
