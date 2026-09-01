# Native human-in-the-loop support, per framework

Survey of what each of the six frameworks Agent Kernel adapts provides natively for
**pause → persist → resume**, at the versions this repo resolves in `ak-py/uv.lock`.

## Verification status

Two different bars apply to the claims below, and they are marked per section:

- **[docs]** — read from the framework's current official documentation during this survey
  (fetched, not remembered). URLs listed at the end.
- **[unverified]** — documented but not import-checked at the time this file was written.

> **Update: the four target frameworks have since been fully verified.** Every symbol below for
> OpenAI, LangGraph, Pydantic AI and Google ADK was import-checked against the exact pinned
> versions — see [`verification.md`](verification.md). All exist; four documentation claims were
> corrected, and they are marked inline below with **[corrected]**. The `[unverified]` markers on
> those four sections should be read as superseded. CrewAI and smolagents were not installed,
> since the design does not depend on their APIs.

Resolved versions (`ak-py/uv.lock`):

| Framework | Pinned version | Declared in `ak-py/pyproject.toml` |
|---|---|---|
| OpenAI Agents SDK | `openai-agents` 0.19.0 | `openai-agents>=0.6.5` |
| LangGraph | `langgraph` 1.0.10 (`langchain` 1.2.10) | `langgraph~=1.0.5` |
| Pydantic AI | `pydantic-ai-slim` 2.13.0 | `pydantic-ai-slim~=2.13.0` |
| Google ADK | `google-adk` 2.5.0 | `google-adk>=1.14.1` |
| CrewAI | `crewai` 1.15.7 | `crewai>=1.15.0` |
| smolagents | `smolagents` 1.26.0 | `smolagents>=1.0.0` |

---

## Summary table

| Framework | Native pause | Serializable pause state | Resume call | Streaming pause | Fit for AK |
|---|---|---|---|---|---|
| **OpenAI Agents SDK** | `needs_approval` on tools → `result.interruptions` | **Yes** — `RunState.to_json()` / `from_json()` | `Runner.run(agent, state)` | **Yes** (documented) | **Strong** |
| **LangGraph** | `interrupt()` → `__interrupt__` in result | **Yes** — in the checkpointer, keyed by `thread_id` | `ainvoke(Command(resume=...), config)` | Yes, via `aget_state` on v2 | **Strong** — AK already owns a checkpointer |
| **Pydantic AI** | `ApprovalRequired` / `CallDeferred` → `DeferredToolRequests` output | **Yes** — `all_messages()` + the requests object | `run(..., message_history=, deferred_tool_results=)` | **Yes** — `DeferredToolRequestsEvent` | **Strong** |
| **Google ADK** | `LongRunningFunctionTool`, or `require_confirmation` on `FunctionTool` | Partial — lives in the ADK session's event history | `run_async(new_message=FunctionResponse)` (+ `invocation_id` when resumable) | **Known-broken upstream** | **Workable, with caveats** |
| **CrewAI** | `@human_feedback` on **Flows** only | Yes, but in CrewAI's own `SQLiteFlowPersistence` | `flow.resume(feedback)` / `Flow.from_pending(id)` | n/a (adapter has no streaming) | **Out of reach** — AK wraps Crews, not Flows |
| **smolagents** | `step_callbacks` + `agent.interrupt()` | No — in-process `agent.memory.steps` only | `agent.run(task, reset=False)` | n/a (adapter has no streaming) | **Weak** — no durable pause |

The four frameworks issue #606 names (OpenAI, LangGraph, Pydantic AI, ADK) are exactly the four
with a durable, programmatic pause. That is not a coincidence, and the two omissions are
justified by the findings below rather than by scope-trimming.

---

## OpenAI Agents SDK — 0.19.0 [docs, symbols unverified at pin]

The most complete story of the six: the SDK ships an explicit durable pause/resume boundary.

**Declaring a gate.** Tools opt in with `needs_approval`, either a bool or a callable receiving
the run context, parsed parameters and the tool call id. Documented as available on
`function_tool`, `Agent.as_tool`, `ShellTool`, `ApplyPatchTool`, and on local MCP servers via
`require_approval`. Callable rules "fail closed when the SDK cannot safely inspect the
arguments".

```python
@tool(needs_approval=True)
async def cancel_order(order_id: int) -> str:
    return f"Cancelled order {order_id}"

async def requires_review(_ctx, params, _call_id) -> bool:
    return "refund" in params.get("subject", "").lower()

@tool(needs_approval=requires_review)
async def send_email(subject: str, body: str) -> str:
    return f"Sent '{subject}'"
```

> **Decorator spelling — [corrected].** The docs page presents `@tool` as the primary spelling,
> but **at the pinned 0.19.0 `agents.tool` is a module, not a callable**. The decorator is
> `agents.function_tool`, and its signature does carry `needs_approval` (as does the
> `FunctionTool` dataclass). AK does not define tools this way — `ToolBuilder.bind()` wraps plain
> functions — so how AK's OpenAI `ToolBuilder` passes `needs_approval` through is still an open
> implementation question, but **which callable to pass it to is settled: `function_tool`**.

**Detecting the pause.** `RunResult.interruptions` / `RunResultStreaming.interruptions` holds
`ToolApprovalItem` entries carrying `agent.name`, `tool_name` and `arguments`.

**Persisting.** `result.to_state()` returns a `RunState` — the documented "durable pause/resume
boundary", holding model responses, generated items, approval state and any server-managed
conversation id. It serialises with `state.to_json()` / `state.to_string()` and restores with
`RunState.from_json(agent, stored)` / `RunState.from_string(...)`.

**Deciding and resuming.**

```python
state = result.to_state()
state.approve(interruption, always_approve=False)
state.reject(interruption, rejection_message="Custom message")
result = await Runner.run(agent, state)          # or Runner.run_streamed(agent, state)
```

`always_approve` / `always_reject` create sticky decisions that survive serialization.

**Streaming.** Explicitly supported: keep consuming `stream_events()` until the iterator
finishes, then inspect `RunResultStreaming.interruptions`, resolve, and resume with
`Runner.run_streamed(agent, state)`.

**Constraints that matter to AK:**

1. `from_json()` **requires the original starting agent** to restore agent context and derive
   stable identities. AK has this — the agent is in `Runtime.agents()` by name — but the paused
   record must store the agent name so the right one is passed back. **[corrected]** the parameter
   is named `initial_agent`; the verified signature is
   `from_json(initial_agent, state_json, *, context_deserializer, context_override, strict_context)`.
2. `RunState` carries a `_schema_version` for restore compatibility. A paused run that outlives
   an SDK upgrade may not restore.
3. Context serialization is documented as "intentionally conservative": mapping contexts
   round-trip, custom types need explicit `context_serializer` / `context_deserializer`.
   **This collides with #526's `framework_context`**, which AK injects as the run `context=`.
4. Resumed runs with a `Session` need "the original Session backend with exclusive history
   access".

## LangGraph — 1.0.10 [docs, symbols unverified at pin]

The canonical implementation, and the one AK is already closest to supporting.

```python
from langgraph.types import interrupt, Command
```

**Pause.** `interrupt(value)` raises internally and surfaces `value` to the caller. In the
`invoke`/`ainvoke` path the result carries `result["__interrupt__"]`. Each `Interrupt` has
`.value` (the payload) and `.id` — both confirmed as its only two fields.

> **[corrected]** Use the literal string `"__interrupt__"`. `langgraph.constants.INTERRUPT` still
> resolves to it but raises `LangGraphDeprecatedSinceV10` — private as of v1.0, slated for removal
> in v2.0.

**Resume.** `Command(resume=value)` passed as the graph input, on the **same `thread_id`**; the
resume value becomes the return value of the original `interrupt()` call. Multiple interrupts
resume by id map: `Command(resume={interrupt_id: response, ...})`.

**Checkpointer is mandatory** — it is what holds the paused state between the two calls.

**Streaming.** The docs recommend `stream_events(input, config, version="v3")`, which exposes
`stream.interrupts` (tuple of `Interrupt`) and `stream.interrupted` (bool). **AK's adapter calls
`astream_events(..., version="v2")`** (`langgraph.py:469-473`), which has no such attribute — on
v2 a pause has to be detected by reading graph state after the stream drains, which AK already
does for another reason at `langgraph.py:481`.

**Documented caveats, all of which AK must pass on to users verbatim:**

- **The node re-runs from the top on resume.** Everything before `interrupt()` executes again,
  so side effects before an `interrupt()` must be idempotent.
- **Never wrap `interrupt()` in `try/except`** inside a node — it pauses by raising, and a
  catch-all swallows it. (This applies inside user nodes; the `ainvoke` call itself returns
  normally with `__interrupt__`, so AK's own `try/except` around `ainvoke` does **not** swallow
  the pause — it loses it a different way, see `adapter-strategies.md`.)
- Do not conditionally skip, or non-deterministically loop, `interrupt()` calls in a node.

## Pydantic AI — 2.13.0 [docs, symbols unverified at pin]

Modelled as **deferred tools** rather than as an interrupt, which makes it the most explicitly
typed of the six.

**Declaring a gate** — three ways:

```python
@agent.tool_plain(requires_approval=True)
def delete_file(path: str) -> str: ...

@agent.tool
def update_file(ctx: RunContext, path: str, content: str) -> str:
    if sensitive and not ctx.tool_call_approved:
        raise ApprovalRequired
    return ...

@agent.tool_plain
async def send_to_worker(task: str) -> str:
    raise CallDeferred          # unconditionally defer to an external executor
```

**Opting in is a typing change, not just a tool change.** `DeferredToolRequests` must be in the
agent's `output_type`, either at construction or per run:

```python
agent = Agent('...', output_type=[str, DeferredToolRequests])
```

**Pause payload.** `DeferredToolRequests` carries `approvals` (list of `ToolCallPart` needing a
human decision), `calls` (list of `ToolCallPart` for external execution), and `metadata`
(`tool_call_id` → context).

**Decision payload.** `DeferredToolResults` carries `approvals` (`tool_call_id` → `bool` |
`ToolApproved(override_args=...)` | `ToolDenied(message=...)`) and `calls` (`tool_call_id` →
result or exception).

> **[corrected]** All four of these — `DeferredToolRequests`, `DeferredToolResults`,
> `ToolApproved`, `ToolDenied` — are **dataclasses, not Pydantic models**. They have no
> `model_fields` and cannot be round-tripped with `model_dump()` / `model_validate()`, which
> directly constrains how the Pydantic AI paused-run payload is serialised.

**Resume:**

```python
result = agent.run_sync(
    'Next instruction',
    message_history=messages,          # from the paused run's result.all_messages()
    deferred_tool_results=results,
)
```

Each resumed run gets a fresh `run_id` but shares the original `conversation_id`.

**Streaming.** Supported and typed: `DeferredToolRequestsEvent` is emitted before a handler runs
and carries the `DeferredToolRequests`; `DeferredToolResultsEvent` when a handler resolves them.
AK's Pydantic AI adapter already consumes `run_stream_events()` (`pydanticai.py:190+`), so these
events arrive on a stream AK is already reading.

**Also available:** `HandleDeferredToolCalls(handler=...)` as an agent capability resolves
deferred calls in-process, with unresolved ones still bubbling up as output. This is the wrong
shape for AK (it re-blocks the run), but it is the right shape for an application that wants to
resolve some calls automatically — worth documenting as a user-side option.

## Google ADK — 2.5.0 [docs, symbols unverified at pin]

Two distinct mechanisms, plus a third that governs durability. This is the framework where the
documentation and the open upstream issues disagree most, so the caveats are load-bearing.

**Mechanism 1 — `LongRunningFunctionTool`.** The tool returns a preliminary `{'status':
'pending', ...}` dict; the runner emits an event whose `long_running_tool_ids` names the pending
call.

```python
from google.adk.tools import LongRunningFunctionTool

def ask_for_approval(purpose: str, amount: float) -> dict[str, Any]:
    return {'status': 'pending', 'approver': 'Sean Zhou',
            'purpose': purpose, 'amount': amount, 'ticket-id': 'approval-ticket-1'}

long_running_tool = LongRunningFunctionTool(func=ask_for_approval)
```

Detection is by matching parts against the event's id set:

```python
def get_long_running_function_call(event: Event) -> types.FunctionCall:
    if not event.long_running_tool_ids or not event.content or not event.content.parts:
        return
    for part in event.content.parts:
        if (part and part.function_call and event.long_running_tool_ids
                and part.function_call.id in event.long_running_tool_ids):
            return part.function_call
```

Resume feeds the completed result back as a `FunctionResponse` on a new message:

```python
updated_response = long_running_function_response.model_copy(deep=True)
updated_response.response = {'status': 'approved'}
async for event in runner.run_async(
        session_id=session.id, user_id=USER_ID,
        new_message=types.Content(parts=[types.Part(function_response=updated_response)],
                                  role='user')):
    ...
```

**Mechanism 2 — action confirmations.** Declarative, and closer to what a UI wants:

```python
FunctionTool(reimburse, require_confirmation=True)

async def confirmation_threshold(amount: int, tool_context: ToolContext) -> bool:
    return amount > 1000
FunctionTool(reimburse, require_confirmation=confirmation_threshold)
```

or, from inside the tool, `tool_context.request_confirmation(hint=..., payload={...})`. ADK then
emits a `FunctionCall` named **`adk_request_confirmation`** carrying the hint and payload, and
the app resumes by sending a `FunctionResponse` with that same id and name and a body of
`{"confirmed": bool, "payload": {...}}`. The tool reads the answer from
`tool_context.tool_confirmation` (`.confirmed`, `.payload`).

**Mechanism 3 — resumability (ADK ≥ 1.16).** Durability is not on by default; it is a property
of the `App`:

```python
app = App(name='my_resumable_agent', root_agent=root_agent,
          resumability_config=ResumabilityConfig(is_resumable=True))
```

With it enabled, ADK persists the `FunctionCall` events before pausing and can restart a
partially completed invocation:

```python
async for event in runner.run_async(user_id='u_123', session_id='s_abc',
                                    invocation_id='invocation-123'):
```

The `invocation_id` comes from the session's event history and **must be the invocation that
produced the pending call**.

**Caveats — the sharpest of any framework here:**

1. **`Runner` must be built from an `App`, not from a bare agent**, for resumability. AK builds
   `Runner(agent=..., app_name=..., session_service=...)` (`adk.py:201`) — no `App` object, so
   `ResumabilityConfig` is currently unreachable.
2. **"Tools in an agent are run at least once, and may run more than once when resuming"** —
   ADK's own documented warning. Idempotency is the user's problem, and AK must say so.
3. **Streaming resume: status unclear, and NOT declared unsupported by Google.** *(Revised — the
   first version of this entry overstated it.)* The issues below were originally cited from search
   results as evidence of a live upstream problem. They were then read directly:
   - [#5064](https://github.com/google/adk-python/issues/5064) — unresolved pause check +
     streaming id mismatch. **Closed.** Against ADK **1.27.3**.
   - [#5349](https://github.com/google/adk-python/issues/5349) — sub-agent sequential LRO tools
     fail to resume. **Closed.** Against ADK **1.27.0–1.30.0**, and **does not involve
     streaming**.
   - [#3567](https://github.com/google/adk-python/issues/3567),
     [#2739](https://github.com/google/adk-python/discussions/2739) — not read; do not rely on
     them.

   **There is no upstream documentation stating that streaming and resume are incompatible.** The
   [ADK resume guide](https://raw.githubusercontent.com/google/adk-docs/main/docs/runtime/resume.md)
   does not mention streaming, `run_live`, `RunConfig` or `StreamingMode` at all. Any claim that
   Google has declared this unsupported is unfounded.

   What *can* be said, from reading 2.5.0's source — see `verification.md` for the detail — is
   that two mechanisms remain which make it an open risk rather than a safe assumption: the
   two-event pause window that ADK's own comment calls "a known limitation", and the
   partial-vs-persisted function-call id split. **Neither has been observed failing at 2.5.0.**
   Decide by test.

## CrewAI — 1.15.7 [docs] — **not reachable through AK's adapter**

CrewAI's own docs present two HITL approaches, and split them by licence:

| Approach | Best for | Version | Licence |
|---|---|---|---|
| Flow-based, `@human_feedback` decorator | local dev, console review, synchronous workflows | 1.8.0+ | Open source |
| Webhook-based | production, async, external integrations | — | **Enterprise / AMP only** |

The open-source flow decorator is genuinely capable:

```python
from crewai.flow.human_feedback import human_feedback
```

with parameters `message` (required), `emit`, `llm`, `default_outcome`, `metadata`, `provider`,
`learn`, `learn_limit`. Default behaviour **blocks on console input**. With an async
`HumanFeedbackProvider`, `kickoff()` instead returns a `HumanFeedbackPending` object and control
returns to the caller; the flow framework **automatically persists state** when
`HumanFeedbackPending` is raised (`SQLiteFlowPersistence` by default, custom persistence
supported), and resume is `Flow.from_pending(flow_id)` then `flow.resume(feedback)` /
`await flow.resume_async(feedback)`.

**Why it is still out of reach.** `@human_feedback` decorates methods on a **`Flow`**. AK's
CrewAI adapter has no Flow anywhere in it: `CrewAIModule` takes a list of CrewAI `Agent` objects
(`crewai.py:544-550`), and `CrewAIRunner.run` builds a fresh `Task` and `Crew` per run and calls
`crew.kickoff_async(inputs={})` (`crewai.py:375-386`). The other option, `Task(human_input=True)`,
blocks on console `input()` — actively wrong inside a server process, and the CrewAI docs do not
document its mechanics at all.

Supporting CrewAI HITL therefore means supporting CrewAI **Flows** as a wrapped object — a
separate change of comparable size to this one, and one that also introduces a second persistence
system (CrewAI's `SQLiteFlowPersistence`) alongside AK's session store.

## smolagents — 1.26.0 [docs] — **no durable pause**

smolagents' documented HITL is a plan-review pattern: register a step callback on `PlanningStep`,
which can interrupt, and resume by re-running with memory preserved.

```python
agent = CodeAgent(model=..., tools=[...], planning_interval=5,
                  step_callbacks={PlanningStep: interrupt_after_plan},
                  max_steps=10, verbosity_level=1)

agent.run(task, reset=True)     # first run, may be interrupted
agent.run(task, reset=False)    # resume with preserved memory
```

State lives in `agent.memory.steps` on the live agent object. There is no pending-tool-call
concept and no serialisable pause record: the callback is expected either to block on console
input or to interrupt and have the operator re-run.

AK's adapter already hydrates and syncs `agent.agent.memory.steps` to the session
(`smolagents.py:98-125`), so a *coarse* pause is conceivable — the paused turn's memory is
already persisted. But there is no framework-level record of *what* was being asked or *which*
call to resume, so any pause payload would be AK-invented rather than framework-native. That is
the line this survey recommends not crossing.

---

## Sources

Fetched during this survey:

- [Human-in-the-loop — OpenAI Agents SDK](https://openai.github.io/openai-agents-python/human_in_the_loop/)
- [Run state — OpenAI Agents SDK](https://openai.github.io/openai-agents-python/ref/run_state/)
- [Tools — OpenAI Agents SDK](https://openai.github.io/openai-agents-python/tools/)
- [Interrupts — LangGraph (LangChain docs)](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [Deferred tools — Pydantic AI](https://pydantic.dev/docs/ai/tools-toolsets/deferred-tools/)
- [Action confirmations — ADK](https://adk.dev/tools-custom/confirmation/)
- [Function tools (LongRunningFunctionTool) — ADK](https://adk.dev/tools-custom/function-tools/)
- [Resume stopped agents — ADK](https://raw.githubusercontent.com/google/adk-docs/main/docs/runtime/resume.md)
- [Human-in-the-Loop — CrewAI](https://docs.crewai.com/en/learn/human-in-the-loop)
- [Human feedback in flows — CrewAI](https://docs.crewai.com/en/learn/human-feedback-in-flows)
- [Plan customization (HITL) — smolagents](https://huggingface.co/docs/smolagents/en/examples/plan_customization)
