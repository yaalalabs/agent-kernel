# Which adapters stream tool-call arguments

Progressive painting needs `ToolCallArgs` to arrive in fragments: the middleware parses partial JSON
as it streams, so an adapter that sends the whole argument blob in one event produces one snapshot
at the end rather than a surface that grows. This is the fidelity table issue #835 asks the docs to
carry.

Verified by reading each adapter on `develop` at `79789c51d`.

| Adapter | Where | Behaviour | Progressive |
|---|---|---|---|
| Claude Agent SDK | `framework/claude/claude.py:257` | One `ToolCallArgs` per `input_json_delta` fragment (`delta["partial_json"]`) | **yes** |
| Pydantic AI | `framework/pydanticai/pydanticai.py:678`, `:710` | Part start emits the args present then; subsequent `args_delta` fragments each emit their own event | **yes** |
| LangGraph | `framework/langgraph/langgraph.py:986` | Whole args in one event at `on_tool_start`, immediately followed by `ToolCallEnd` | no |
| Google ADK | `framework/adk/adk.py:887` | Whole args at the function-call event, then `ToolCallEnd` | no |
| OpenAI | `framework/openai/openai.py:603` | Whole args on the `tool_called` item, then `ToolCallEnd`. By design — see `docs/specs/523-ag-ui-support/plan.md:350` | no |
| Microsoft Agent Framework | `framework/maf/maf.py:636-653` | Chunk-based: `ToolCallStart` guarded by `open_calls`, then one `ToolCallArgs` per streamed chunk; SDK chunks carry fragments | **yes** |
| CrewAI | `framework/crewai/` | Emits no tool-call stream events at all | not supported |
| smolagents | `framework/smolagents/` | Emits no tool-call stream events at all | not supported |

## Notes

- **"no" still renders.** A whole-args adapter produces a single `ACTIVITY_SNAPSHOT` when the tool
  result arrives, so the surface appears — it just does not grow while the model writes. The
  acceptance criterion is "progressive on at least one adapter", and Claude and Pydantic AI are
  that one.
- **MAF confirmed against the SDK.** `_function_call_events` guards `ToolCallStart` with
  `open_calls` and appends a `ToolCallArgs` per chunk. On the SDK side,
  `_coalesce_function_call_occurrences` is documented as *"Merge streamed function-call fragments
  that share a stable occurrence id"* and merges them with `Content.__add__`, whose function-call
  branch concatenates string arguments outright (`arguments = self_arguments + other_arguments`) —
  `agent_framework/_types.py:2414` and `:1742-1763`, read at `agent-framework-core` 1.20.0 in
  `ak-py/.venv`. A provider sending whole arguments per chunk would produce a corrupt
  concatenation, so fragments are the contract.
- **CrewAI and smolagents cannot use this route**, and not because of this change: neither adapter
  emits `ToolCallStart` / `ToolCallArgs` / `ToolCallResult` at all (`grep` over both packages
  returns nothing), and both still raise `NotImplementedError` from `stream()`. PR #909 adds token
  streaming to them, which is text — it does not add tool-call events.
