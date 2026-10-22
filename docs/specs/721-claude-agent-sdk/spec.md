# #721: Claude Agent SDK integration — Implementation Spec

This describes how the [design](design.md) maps the Claude Agent SDK onto Agent Kernel's existing `Agent`, `Runner`, `Module`, `ToolBuilder`, and `Session` contracts. It records the intended behavior of the implementation on this branch, including the later native-subagent, context, tracing, and human-approval work. A unit test with a fake SDK client does not replace the credentialed checks called out below.

## Design

### Package and public API

| Location | Responsibility |
| --- | --- |
| `ak-py/src/agentkernel/framework/claude/claude.py` | Framework state, SDK bridge, stream mapper, runner, agent wrapper, module, and tool builder. |
| `ak-py/src/agentkernel/framework/claude/__init__.py` | Export `ClaudeAgentSpec`, `ClaudeModule`, `ClaudeToolBuilder`, `ClaudeToolContext`, and `ClaudeTelemetry`. |
| `ak-py/src/agentkernel/claude.py` | Keep the short `agentkernel.claude` import path. |
| `ak-py/src/agentkernel/trace/{langfuse,logfire,openllmetry,cloudwatch}/claude.py` | Framework-specific traced runners selected by the existing trace interface. |

- Keep Claude SDK imports inside the adapter and Claude tracing modules. `core/` must not import the Claude SDK or depend on Claude-specific session data.
- Keep `claude` as the optional package extra in `ak-py/pyproject.toml`. Loading the adapter requires that extra; other framework imports do not.
- No new framework-neutral agent model, provider factory, or session backend is introduced. `ClaudeModule` is the same registration seam used by the other framework modules. A new pluggable backend is not being created.
- In `claude.py`, place `ClaudeSession` and `_ClaudeSessionStore` before runner helpers, followed by `ClaudeRunner`, `ClaudeAgentSpec`/`ClaudeAgent`, `ClaudeModule`, and `ClaudeToolBuilder`. Helpers may sit before their consumer when Python needs them there.

### Main agent and native subagents

```python
@dataclass
class ClaudeAgentSpec:
    name: str
    description: str = ""
    options: ClaudeAgentOptions = field(default_factory=ClaudeAgentOptions)
    tools: list[SdkMcpTool] = field(default_factory=list)

class ClaudeModule(Module):
    def __init__(self, agents: list[ClaudeAgentSpec], runner: ClaudeRunner | None = None) -> None: ...
```

- `ClaudeAgentSpec` adds the AK registration name, description, and in-process tools that the main `ClaudeAgentOptions` does not hold together. The options remain native SDK configuration.
- `ClaudeAgent` copies the options and tool list when wrapping a declaration. System-tool attachment and prompt overrides must not mutate another agent's shared declaration. An agent without `name` fails during module loading.
- Native subagents are declared only through `ClaudeAgentOptions.agents: dict[str, AgentDefinition]`. There is no parallel `ClaudeAgentSpec.subagents` conversion. A native subagent remains inside its parent's SDK run and is not an independently registered AK agent.
- If `options.agents` has entries, `_native_options()` makes the native `Agent` tool available and adds it to allowed tools. Other native subagent fields pass through intact. An AK tool exposed to a subagent uses its `mcp__ak__<name>` name.
- `ClaudeModule` uses an explicit runner when given; otherwise it resolves the existing configured tracing runner or creates `ClaudeRunner`. It registers `ClaudeAgent` wrappers through the base `Module` flow.

### Session and SDK transcript bridge

```python
class ClaudeSession:
    def session_id(self, agent_name: str) -> str | None: ...
    def transcript(self, agent_name: str) -> dict[str, list[dict]]: ...
    def save(self, agent_name: str, session_id: str, transcript: dict[str, list[dict]]) -> None: ...

class _ClaudeSessionStore:
    async def append(self, key: Mapping[str, Any], entries: list[dict]) -> None: ...
    async def load(self, key: Mapping[str, Any]) -> list[dict] | None: ...
    async def list_subkeys(self, key: Mapping[str, Any]) -> list[str]: ...
    def commit(self, session_id: str) -> None: ...
```

- `ClaudeRunner._session()` gets or creates one `ClaudeSession` under `Session.get("claude")` / `Session.set("claude", ...)`. That object stores IDs and plain JSON transcript entries by AK agent name. The empty subpath is the main transcript; named subpaths hold native subagent transcripts. No live `ClaudeSDKClient` is serialized.
- Each run creates a short-lived `_ClaudeSessionStore` around one agent's `ClaudeSession` entry. Its `append()` buffers entries and skips UUIDs already saved or buffered; `load()` returns saved plus pending entries; `list_subkeys()` exposes subagent transcripts. The SDK's project key is ignored because the bridge is already scoped to the AK session and agent.
- `_native_options()` gives the SDK this store with batched flushing. With no saved main transcript it assigns a fresh native session ID; with a saved main transcript it sets `resume` to the stored ID. The AK session ID and native Claude session ID remain distinct.
- After a complete `ResultMessage`, `commit(result.session_id)` saves the buffered transcript, including a complete error result. A missing result or an abandoned stream does not commit. The configured AK session backend persists the enclosing `Session` after the runtime call.
- A second AK agent name in the same session has its own native ID and transcript. Resume on another worker depends on the configured AK session backend carrying the complete transcript, not only the ID.
- Transcript size grows with conversation length. The adapter has no compaction or separate transcript backend policy in this change; the design's size question remains open.

### Runner, options, input, and output

- `ClaudeRunner.run()` and `stream()` resolve the agent's run options once, create the per-run context and SDK store, open a new `ClaudeSDKClient` in an async context manager, call `query()`, and read the SDK response. `resume()` and `resume_stream()` use the same client lifecycle after validating a paused record.
- `_native_options()` copies `ClaudeAgentOptions`, overlays resolved native run options, and writes AK-owned conversation, session-store, and stream fields last. `ClaudeAgent.validate_run_options()` rejects caller declarations of those reserved fields, unknown option names, and an MCP server configuration incompatible with the AK tool server. A caller's other native options, hooks, and MCP servers remain available.
- Text requests become a string prompt. Image and document requests become one native streaming-input user message. HTTPS media URLs and supported base64 media are accepted; S3 references, missing media types, and unsupported file types yield clear errors. An empty ordinary request returns a no-content reply before resolving run options.
- A text result becomes `AgentReplyText`; a native structured output becomes `AgentReplyAny`. A complete SDK error result is converted to the normal AK user-facing error path while its transcript remains committed. A run with no result raises an error before commit.
- `_ClaudeStreamMapper` is constructed per streamed run. It maps real native text, reasoning, tool-call, and tool-result messages to AK `StreamEvent`s, retains native IDs, and omits internal subagent traffic. Closing a stream early disconnects the SDK client and does not commit a partial transcript.

### Bound tools and per-run context

- `ClaudeToolBuilder.bind()` converts Python functions to SDK `SdkMcpTool`s with a schema from their signatures and optional SDK tool annotations. Variadic parameters and non-callables fail at bind time. Synchronous functions execute on a worker thread.
- The runner serves bound tools through one in-process SDK MCP server named `ak`. It adds the server beside caller-supplied servers and approves ordinary bound tools by their native `mcp__ak__<name>` names. The name `ak` is reserved from caller MCP server declarations.
- `ClaudeToolContext.get()` exposes a copy of AK's `framework_context` only while a bound tool runs. The runner stores changed keys back after a successful run or fully drained stream. Built-in Claude tools and external MCP servers cannot read this Python context handle. A failed run or early stream close leaves the stored context unchanged.
- `ToolContext` is set for the SDK client lifetime and reset afterward. Context variables and the stream mapper belong to one run, not to the shared runner instance.

### Human approval and resume

- A bound tool declared with `needs_approval=True` receives a `PreToolUse` hook that asks the SDK to `defer` the call. The adapter merges this hook with caller hooks. A per-run `_ClaudeApprovalGuard` also requires a matching one-use approval inside the tool handler, so an SDK permission mode that ignores `defer` cannot execute the tool unchecked.
- On a `ResultMessage` with one deferred tool use, commit the transcript and create an AK `PausedRun` with the tool call ID, native session ID, and main-transcript position. Replace only an older pause for the Claude runner; leave another framework's pause alone.
- Before resume, reject a missing or advanced transcript, a decision for anything other than the single deferred call, and an approved payload that is not a JSON object. Approved decisions allow the call, optionally with updated input; denied and cancelled decisions deny it with their respective messages.
- A completed resume clears its paused record; a failed resume keeps it retryable. A new defer during resume supersedes the earlier record. Streamed pause/resume emits AK's pause event and closes stream boundaries.
- The SDK's `defer` behavior and the exact resumed tool call still require a credentialed live run. `ak-py/tests/test_claude_hitl_live.py` is opt-in and skipped without credentials.

### Tracing, configuration, and consumer changes

- The four Claude tracing adapters wrap `run`, `resume`, `stream`, and `resume_stream` so their outer spans cover execution and stream iteration. Python-side instrumentation cannot expose model calls performed inside the CLI subprocess.
- `ClaudeTelemetry.enable_traces()` returns opt-in environment variables for the CLI's own OpenTelemetry export. The application merges them into native `ClaudeAgentOptions.env` or declared run options; the adapter does not silently enable CLI telemetry.
- No `AKConfig` fields change. Existing `session` and `trace` configuration selects persistence and AK tracing. Existing YAML and `AK_*` environment variables retain their meaning.
- CLI, API, and run-options examples use the public `agentkernel.claude` import path and native `ClaudeAgentOptions`; the framework page documents the process, permissions, subagents, sessions, context, and tracing boundaries.

## Behavioural changes and compatibility

1. Native `options.agents` replaces the branch's earlier partial `ClaudeAgentSpec.subagents` conversion. Branch examples using the old field must change; `AgentDefinition` fields now reach the SDK unchanged.
2. Gated AK tools pause through `defer` and refuse execution without a matching one-use approval. This is an explicit opt-in through `needs_approval=True`.
3. Claude tracing wrappers now cover resume and both streamed paths, in addition to ordinary runs.

**Non-changes:** The AK `Session` API, configured session backends, trace selection, core event types, and native SDK option defaults are unchanged. There is no new persistent data migration beyond the branch's Claude session data.

## Error handling

- Declaration errors (missing name, reserved or unknown run option, MCP server collision, invalid tool signature) fail at declaration or module load with an actionable exception.
- Unsupported request media becomes an AK error reply in `run()` or propagates through the stream path, matching the respective runner contract.
- SDK/client failure before a complete result does not commit pending transcript entries. A complete SDK error result commits its transcript and reports the SDK error.
- Invalid resume decisions and stale saved conversations fail before entering the SDK client and preserve the pause record.
- A tool awaiting approval returns an SDK tool error if invoked without a matching one-use grant. This remains enforced when the SDK's `defer` is not honored.

## Testing and acceptance

- `ak-py/tests/test_claude_runner.py` patches `agentkernel.framework.claude.claude.ClaudeSDKClient` with `FakeClient`. Cover first/resumed turns, serialized session restore, agent isolation, transcript buffer/commit, native options and subagents, input/output mapping, stream close, context write-back, pause, and resume.
- `ak-py/tests/test_tool_claude.py` covers tool schemas, annotations, validation, sync/async handlers, names, and `needs_approval` metadata.
- `ak-py/tests/test_claude_traced_runner.py` patches `ClaudeRunner.resume`, `stream`, and `resume_stream` and checks trace contexts remain active through streamed iteration in each tracer.
- `ak-py/tests/test_claude_hitl_live.py` is an opt-in credentialed check for an actual Claude CLI pause and resume. Before production claims, also run a credentialed two-turn session and native subagent flow, including a resumed turn after reloading the AK session from the configured backend.
- Run the focused tests from `ak-py` with `uv run pytest tests/test_claude_runner.py tests/test_tool_claude.py tests/test_claude_traced_runner.py`; run the repo's `make lint-check-all` gate before merge. Credentialed examples and live tests require the corresponding local credentials and runtime.
