# #525: Store token usage on the Session (last run + session total)

After every agent run, AK records how many requests and tokens the run used and saves them on the
`Session`. Two numbers are kept: the **last run's usage** and the **running total for the whole session**.
Hooks read them through two `Session` accessors, the same way they read `framework_context` today.
Each framework adapter translates its own native usage object into one shared AK model.

## Motivation

- AK has no usage API. `grep -i usage` across `framework/` and `trace/` finds no token reads.
- Each adapter receives native usage and throws it away:
  - OpenAI keeps only `.final_output` and discards the `RunResult` together with
    `result.context_wrapper.usage` (`framework/openai/openai.py:216`).
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
  - Fields: `requests`, `input_tokens`, `output_tokens`, `total_tokens`. All are `int` and default to `0`.
  - Supports `+` so two usages can be added together. `+` returns a new instance.
  - Frozen (immutable), so a hook cannot change the stored numbers by editing the object it reads.
- New Pydantic model `SessionUsage`:
  - `last_run: AgentUsage | None`. `None` means the last run reported no usage. It is different from all zeros.
  - `total: AgentUsage`. It starts at all zeros.
- Both models must be picklable, because sessions are persisted with pickle (`core/session/serde.py`).

### Session accessors

- Add the reserved key `Session.Keys.USAGE = "usage"`.
- Add `session.get_last_usage() -> AgentUsage | None` and `session.get_total_usage() -> AgentUsage`.
  - Both are read-only and never raise.
  - On a fresh session, `get_total_usage()` returns zeros and `get_last_usage()` returns `None`.
- No public setter. The key is written only through two private helpers:
  - `Session._reset_last_usage()`: called by `Runtime` (see Recording rule).
  - `Runner._record_usage(...)`: called by the adapters.
- Callers never spell the raw key.

### Recording rule

- The base `Runner` gets one helper, `_record_usage(session, usage: AgentUsage | None)`:
  - It sets `last_run = usage`.
  - When `usage` is not `None`, it also adds `usage` to `total`.
- Each adapter has one job: convert its native usage object to `AgentUsage` and call `_record_usage` once per run.
  - **Success only**: call it after the native call completes, inside the `try`, as `_store_framework_context` does.
  - It must not sit inside the `if incoming is not None` guard (`langgraph.py:483`, `:543`; `adk.py:306`, `:407`).
    Otherwise usage is skipped whenever no framework context is set.
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
| Pydantic AI | `result.usage()` (`RunUsage`) | `run_result.usage()` from the final event | All 4 native (`total_tokens` is a computed property) |
| LangGraph | Sum `usage_metadata` of the **new** `AIMessage`s only (`result["messages"]` includes history); `requests` = number of new AIMessages | Sum `usage_metadata` from `on_chat_model_end` events | `usage_metadata` may be `None`, depending on provider settings. Zero usage then comes from the provider config, not from AK. |
| Google ADK | Sum `event.usage_metadata` over non-partial events (`prompt_token_count` → input, `candidates_token_count + thoughts_token_count` → output); `requests` = count of those events | Same, over the streamed events | `get_response` (`adk.py:250`) must also return usage. No traced runner overrides it. |
| CrewAI | `CrewOutput.token_usage` (`prompt_tokens`, `completion_tokens`, `successful_requests`) minus the same sum taken over the agents just before `kickoff_async` | n/a: CrewAI does not stream | The value sums each agent LLM's lifetime counters (`Crew.calculate_usage_metrics`). The agents outlive the per-run `Crew`, so the value grows every turn and needs a difference. |
| smolagents | Sum `step.token_usage` over the memory steps this run added | n/a: smolagents does not stream | `agent.monitor` keeps a total across turns (`run(..., reset=False)`), so the adapter does not read it. `requests` is **derived** from the number of steps added, because smolagents has no request count. |

- Traced runners (Langfuse, OpenLLMetry, Logfire) all delegate to `super().run`, so they need no change.

### Persistence and lifecycle

- `usage` is an ordinary durable session key. `store()` saves it with no extra plumbing.
- `Session.clear()` (`base.py:236`) rebuilds the data with only the two caches, so it **resets usage** as well.
  - This is intended: clearing the session (e.g. the CLI's `!clear`) starts a new conversation.
- A stream halted by `StreamHalt` skips `store()`. On a durable store, that turn's usage is lost along with the rest of the session update.

### Configuration

- **No new configuration.** Usage is always recorded. It is cheap and has no external dependency.

### Docs / example

- Add a short "Reading usage" section to the hooks docs.
- Add one example post-hook that logs `session.get_last_usage()` and `session.get_total_usage()`.

## Non-goals

- **Per-tool-call usage.** The issue mentions it, but no framework reports tokens per tool. Left for a follow-up.
- Cached and reasoning token counts.
- Cost or price calculation.
- Returning usage on `AgentReply`, `StreamChunk` or the REST/WS response.
- A per-agent or per-sub-agent breakdown. The total is session-wide.
- Recording partial usage from failed runs.

## Open questions

- None. All decisions are resolved above.
