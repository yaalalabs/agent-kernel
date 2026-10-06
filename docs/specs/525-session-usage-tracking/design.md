# #525: Store token usage on the Session (last run + session total)

After every agent run, AK records how many requests and tokens the run used and saves them on the
`Session`. Two numbers are kept: the **last run's usage** and the **running total for the whole session**.
Hooks read them through two `Session` accessors, the same way they read `framework_context` today.
Each framework adapter translates its own native usage object into one shared AK model.

## Motivation

- AK has no usage API. `grep -i usage` across `framework/` and `trace/` finds no token reads.
- Each adapter receives native usage and throws it away:
  - OpenAI keeps only `.final_output` and discards the `RunResult` together with
    `result.context_wrapper.usage` (`framework/openai/openai.py:217`).
  - Pydantic AI receives an `AgentRunResult` with `.usage()` and does not read it (`framework/pydanticai/pydanticai.py:194`).
  - CrewAI's `CrewOutput.token_usage` is ignored (`framework/crewai/crewai.py:384`).
  - ADK's `get_response` loop drops every event, and its `usage_metadata` with it (`framework/adk/adk.py:269`).
  - LangGraph's `AIMessage.usage_metadata` is never summed (`framework/langgraph/langgraph.py:480`).
  - smolagents returns only the final answer (`framework/smolagents/smolagents.py:170`).
- The issue asks for usage per session for cost tracking, monitoring and debugging, which brings AK in line with the OpenAI SDK.
- The Session already holds AK-owned data under reserved keys with named accessors
  (`Session.Keys`, `core/base.py:42`; `get_framework_context()`, `base.py:188`). A usage key follows the same pattern.
- Hooks already receive the session: `PreHook.on_run` and `PostHook.on_run` (`core/hooks.py:42`, `:72`).
  Post-hooks run after the runner and before `store()` (`core/runtime.py:286-295`).
  So usage the runner writes is visible to the post-hook in the same turn and is saved along with the session.

## Requirements

### Data model (core)

- New Pydantic model `AgentUsage` in `core/model.py`:
  - Stored fields: `requests`, `input_tokens`, `output_tokens`. All are `int` and default to `0`.
  - `total_tokens` is a computed property, always `input_tokens + output_tokens`. It is not a stored field,
    so no instance can carry a total that disagrees with its parts.
  - Supports `+` so two usages can be added together. `+` adds the three stored fields and returns a new instance.
  - Frozen (immutable), so a hook cannot change the stored numbers by editing the object it reads.
- New Pydantic model `SessionUsage`:
  - `last_run: AgentUsage | None`. `None` means the last run reported no usage. It is different from all zeros.
  - One rule decides which an adapter records:
    - `None` when the native result exposes **no usage data at all**. Each case is named in the mapping table.
    - An `AgentUsage` (possibly all zeros) when the framework reported usage, even if every count is zero.
    - `None` also when converting the native usage fails (see Recording rule).
  - `total: AgentUsage`. It starts at all zeros.
- Both models must be picklable, because sessions are persisted with pickle (`core/session/serde.py`).

### Session accessors

- Add the reserved key `Session.Keys.USAGE = "usage"`.
- Add `session.get_last_usage() -> AgentUsage | None` and `session.get_total_usage() -> AgentUsage`.
  - Both are read-only and never raise.
  - On a fresh session, `get_total_usage()` returns zeros and `get_last_usage()` returns `None`.
  - If the key holds something other than a `SessionUsage`, both treat it as absent and log one warning.
    - This can happen when an existing app already stored its own `"usage"` value through the public `Session.set()`.
    - The first recorded run overwrites that value. No app code in `ak-py/src` or `examples/` uses the key today.
- No public setter. Both writers are private methods on `Session`:
  - `Session._reset_last_usage()`: called by `Runtime` (see Recording rule).
  - `Session._record_usage(usage: AgentUsage | None)`: called through `Runner._record_usage`.
- The raw key name appears nowhere outside `Session`, the base `Runner` included. This is the same rule as
  `framework_context` (#526).

### Recording rule

- The base `Runner` gets one helper, `_record_usage(session, usage: AgentUsage | None)`. It delegates to
  `Session._record_usage`, which:
  - sets `last_run = usage`;
  - when `usage` is not `None`, also adds `usage` to `total`.
- Each adapter has one job: convert its native usage object to `AgentUsage` and call `_record_usage` once per run.
- **"Success" means the native framework call completed.** Record right after it returns (after the drain, for a
  stream), **before** AK converts the native result into a reply.
  - If AK's own reply conversion fails afterwards (e.g. `AgentReplyAny.from_output`, `openai.py:221`;
    `langgraph.py:487-491`), the tokens still count. They were spent, and the user still gets an error reply.
  - If the native call raises, nothing is recorded.
  - It must not sit inside the `if incoming is not None` guard (`langgraph.py:483`, `:543`; `adk.py:306`, `:407`).
    Otherwise usage is skipped whenever no framework context is set.
- **Recording never raises**, on `run()` or `stream()`.
  - Converting and recording run inside one log-not-raise guard, like the stream write-back of
    `framework_context` (`openai.py:278-281`).
  - On failure: log at ERROR with the session id, then record `None`.
  - Why it matters on `run()`: a usage bug would otherwise turn a successful reply into an error reply.
  - Why it matters on `stream()`: `Runtime.stream` catches only `StreamHalt` (`runtime.py:366`). Any other
    exception skips `store()` (`:364`), so the whole turn's session update would be lost.
- `Runtime.run` / `Runtime.stream` call `session._reset_last_usage()` after pre-hooks and before calling the runner. This sets `last_run` to `None`.
  - Pre-hooks still see the **previous** run's numbers.
  - A failed run, or a run with no usage, leaves `last_run = None` rather than a stale value.
- If a pre-hook halts the run, the runner never runs. Usage is left unchanged.
- Failed runs record nothing. The session total is a **lower bound** on what was spent, and the docs say so.
- Concurrency: the session lock (`async with session`) is held for the whole run, so adding to `total` is not racy.
  - The CrewAI difference reads counters on native objects that all sessions share (see the mapping table).
    If two sessions run on the same native agent at once, they can count each other's tokens.
    This is a known limitation and the docs state it.

### When hooks can see it

- **`run()`**: post-hooks see this run's `last_run` and the updated `total`.
- **`stream()`**: usage is recorded once, after the stream drains normally, the same rule `framework_context` uses.
  - Streamed post-hooks only get `on_stream_event`, so the current turn's hooks never see it.
  - The next turn's pre-hook does. *(User decision.)*
- Disconnect or exception mid-stream: nothing is recorded.

### Per-framework mapping

AK's `total_tokens` is always `input_tokens + output_tokens`. This keeps frameworks comparable.
`output_tokens` includes reasoning or thinking tokens on every framework, as OpenAI's does natively.

| Framework | Source (run) | Source (stream) | Notes |
|---|---|---|---|
| OpenAI | `RunResult.context_wrapper.usage` (keep the result, not just `.final_output`) | `RunResultStreaming.context_wrapper.usage` after the drain | All 4 fields native |
| Pydantic AI | `result.usage()` (`RunUsage`) | `run_result.usage()` from the final event | All 4 native. **`None`** when a stream drains without an `agent_run_result` event (the adapter already warns, `pydanticai.py:268`). |
| LangGraph | Sum `usage_metadata` of the **new** `AIMessage`s only (`result["messages"]` includes history); `requests` = number of new AIMessages | Sum `usage_metadata` from `on_chat_model_end` events; `requests` = number of those events | `usage_metadata` may be `None`, depending on provider settings. **`None`** when no new message (or event) carries `usage_metadata`. |
| Google ADK | Sum `event.usage_metadata` over non-partial events (`prompt_token_count` → input, `candidates_token_count + thoughts_token_count` → output); `requests` = count of those events | Same, over the streamed events | **`None`** when no event carries `usage_metadata`. The public `get_response` (`adk.py:250`) **keeps its signature and `str` return**: tests assert and mock it. A new private helper returns `(text, usage)`; `run()` calls the helper, and `get_response` calls it and drops the usage. |
| CrewAI | `CrewOutput.token_usage` (`prompt_tokens` → input, `completion_tokens` → output, `successful_requests` → requests) minus the same sum taken over the agents just before `kickoff_async` | n/a: CrewAI does not stream | The value sums each agent LLM's lifetime counters (`Crew.calculate_usage_metrics`). The agents outlive the per-run `Crew`, so the value grows every turn and needs a difference. The adapter does the subtraction itself, **clamped at zero per field**. It is the same rule as `UsageMetrics.delta_since`, but that method isn't in every version the `crewai>=1.15.0` pin allows. `reasoning_tokens` is **not** added: CrewAI fills it from `completion_tokens_details` (`crewai/llm.py:2136`), so it is already part of `completion_tokens`. **`None`** when `token_usage` is missing. |
| smolagents | Sum `step.token_usage` over the memory steps this run added | n/a: smolagents does not stream | `agent.monitor` keeps a total across turns (`run(..., reset=False)`), so the adapter does not read it. `requests` is **derived**, because smolagents has no request count. It is the number of added steps whose `token_usage` is not `None`. Every run also adds a `TaskStep` with no usage (`smolagents/agents.py:488`), and that step must not count. **`None`** when no added step has `token_usage`. |

- Traced runners (Langfuse, OpenLLMetry, Logfire) all delegate to `super().run`, so they need no change.

### Persistence and lifecycle

- `usage` is an ordinary durable session key. `store()` saves it with no extra plumbing.
- `Session.clear()` (`base.py:236`) rebuilds the in-memory data with only the two caches, so the loaded
  session's usage is reset. This is intended: clearing the session (e.g. the CLI's `!clear`) starts a new conversation.
  - **Known limitation on durable stores:** Redis and DynamoDB `store()` only upsert the keys present
    (`redis.py:100-101`, `dynamodb.py:105-107`) and never delete removed ones. `AgentService.clear()`
    (`service.py:119`) does not store anything either.
  - So after a reload, the old usage key comes back from Redis or DynamoDB.
  - This already applies to every session key (`framework_context`, each framework's state). It is not specific
    to usage, and fixing it is out of scope here (see Non-goals).
- A stream halted by `StreamHalt` skips `store()`. On a durable store, that turn's usage is lost along with the rest of the session update.

### Configuration

- **No new configuration.** Usage is always recorded. It is cheap and has no external dependency.

### Documentation and skills

- `docs/docs/core-concepts/session.md`: document the `usage` reserved key and the two accessors, next to
  "Framework context / per-run state" (`:411`). Cover the `None`-vs-zeros rule, the lower-bound rule, and the
  durable-store `clear()` limitation.
- `docs/docs/integrations/hooks.md`: a short "Reading usage" section that links to the session page.
  It explains that streamed usage is visible from the next turn.
- `docs/docs/core-concepts/runner.md` and the framework pages under `docs/docs/frameworks/`: the per-framework
  caveats. These are the CrewAI shared counters, LangGraph's provider-dependent `usage_metadata`, smolagents'
  derived `requests`, and ADK's output including thinking tokens.
- `.agents/skills/ak-dev-architecture/SKILL.md`: add the `USAGE` key to Session's reserved keys, and add
  `Runner._record_usage` to the Runner helpers.
- Example: add a usage-logging `PostHook` to `examples/api/hooks/hooks.py`, beside `DisclaimerHook`, instead of a new example directory.

### Testing

- `AgentUsage`:
  - `total_tokens` always equals input + output.
  - `+` returns a new instance with summed fields.
  - The model is frozen, and both models survive a pickle round-trip.
- `Session` accessors:
  - A fresh session returns zeros and `None`.
  - A foreign value under `"usage"` is treated as absent, with one warning.
  - Neither accessor ever raises.
- Recording and reset semantics through `Runtime.run`:
  - The total accumulates across turns.
  - A pre-hook sees the previous run, and a post-hook sees the current one.
  - A pre-hook halt leaves usage unchanged.
  - A native-call failure gives `last_run = None` with the total unchanged.
  - A reply-conversion failure after the native call still records.
  - A failure inside usage conversion logs and records `None`, and the reply is unaffected.
- Streaming through `Runtime.stream`:
  - Usage is recorded after a normal drain.
  - Nothing is recorded on a disconnect or a mid-stream exception.
  - A usage-conversion failure does not skip `store()`.
- Durable round-trip: usage survives `store()` and a reload on the in-memory store and a mocked durable store.
- One mapping test per adapter (native result → `AgentUsage`), covering at minimum:
  - LangGraph: only new messages are summed.
  - ADK: partial events are ignored and thinking tokens are added.
  - CrewAI: the before/after difference is clamped at zero.
  - smolagents: the `TaskStep` is excluded from `requests`.
  - Every adapter: the case that produces `None`.
- ADK: the existing `get_response` tests (`tests/test_adk_runner.py`, `tests/test_tool_adk.py`) pass unchanged.

## Non-goals

- **Per-tool-call usage.** The issue mentions it, but no framework reports tokens per tool. Left for a follow-up.
- Cached and reasoning token counts.
- Cost or price calculation.
- Returning usage on `AgentReply`, `StreamChunk` or the REST/WS response.
- A per-agent or per-sub-agent breakdown. The total is session-wide.
- Recording partial usage from failed runs.
- Making `Session.clear()` delete keys from durable stores. That is an existing gap for every session key.

## Open questions

- None. All decisions are resolved above.
