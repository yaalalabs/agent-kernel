# Symbol verification against the pinned framework versions

The survey in [`framework-hitl-survey.md`](framework-hitl-survey.md) was written from official
documentation. This file records the result of **import-checking every symbol the design depends on**
against the exact versions `ak-py/uv.lock` resolves, which is what closes the two gaps
`README.md` listed as gating `spec.md`.

## How it was run

The framework packages are not installed in the repo's own environment, so a throwaway venv was
created outside the repo and the four target frameworks installed at their locked versions:

```
uv venv hitl-verify --python 3.12
uv pip install "openai-agents==0.20.0" "langgraph==1.2.11" \
               "pydantic-ai-slim==2.13.0" "google-adk==2.8.0" \
               "ag-ui-protocol==0.1.22"
```

Versions reported by the venv at run time — matching `uv.lock` exactly:

| Package | Version |
|---|---|
| `openai-agents` | 0.20.0 |
| `langgraph` | 1.2.11 |
| `pydantic-ai-slim` | 2.13.0 |
| `ag-ui-protocol` | 0.1.22 |
| `google-adk` | 2.8.0 |

**Result: every symbol and source-level claim the design relies on holds at the pinned versions.**
The probe was **re-run in full after the `develop` merge bumped four pins** (`openai-agents`
0.19.0→0.20.0, `langgraph` 1.0.10→1.2.11, `google-adk` 2.5.0→2.8.0, `ag-ui-protocol`
0.1.20→0.1.22): **20/20 checks pass, 0 failures**, including the four ADK *source-level* reads
the design's requirements rest on. Nothing in the design changed as a result.

## Results

### OpenAI Agents SDK 0.20.0 — all present

| Symbol | Verified |
|---|---|
| `agents.function_tool(needs_approval=...)` | present — full param list includes `needs_approval` |
| `agents.tool.FunctionTool.needs_approval` | present as a dataclass field |
| `RunResult.interruptions: list[ToolApprovalItem]` | present (`agents/result.py:447`, `field(default_factory=list)`) |
| `RunResultStreaming.interruptions` | present (`agents/result.py:579`) |
| `RunResult.to_state()` | present (`agents/result.py:473`) |
| `RunResultStreaming.to_state()` | present (`agents/result.py:977`) |
| `RunState.approve / reject / to_json / from_json / to_string / from_string` | all present |
| `ToolApprovalItem` | `arguments`, `call_id`, `name`, `qualified_name` are **properties derived from `raw_item`**, not dataclass fields (they moved between 0.19.0 and 0.20.0); still readable, so `PausedInterruption.arguments` is unaffected |
| `Runner.run(...)` | accepts `input` (a `RunState` may be passed here) and `starting_agent` |

The SDK's own docstring on `to_state` states the intended pattern verbatim, which is the pattern
the design adopts:

```
if result.interruptions:
    state = result.to_state()
    state.approve(result.interruptions[0])
```

### LangGraph 1.2.11 — all present

| Symbol | Verified |
|---|---|
| `from langgraph.types import interrupt, Command, Interrupt` | all importable |
| `Interrupt` fields | `id`, `value` — exactly as documented |
| `Command` fields | include `resume` (also `goto`, `update`, `graph`, `PARENT`) |
| `"__interrupt__"` result key | confirmed as the value of the internal constant |

### Pydantic AI 2.13.0 — all present

| Symbol | Verified |
|---|---|
| `pydantic_ai.DeferredToolRequests` | dataclass with `calls`, `approvals`, `metadata` |
| `pydantic_ai.DeferredToolResults` | dataclass with `calls`, `approvals`, `metadata` |
| `pydantic_ai.ToolApproved` | dataclass with `override_args`, `kind` |
| `pydantic_ai.ToolDenied` | dataclass with `message`, `kind` |
| `pydantic_ai.ApprovalRequired` / `CallDeferred` | both importable |
| `Agent.run(deferred_tool_results=..., message_history=...)` | both parameters present |
| `Agent.tool_plain(requires_approval=...)` | present |
| `pydantic_ai.messages.DeferredToolRequestsEvent` | importable |

### Google ADK 2.8.0 — all present, **including the blocker**

| Symbol | Verified |
|---|---|
| `google.adk.apps.App` | fields `name`, `root_agent`, `resumability_config`, `plugins`, `context_cache_config`, `events_compaction_config` |
| `google.adk.apps.ResumabilityConfig` | field `is_resumable` |
| `google.adk.tools.LongRunningFunctionTool` | importable |
| `google.adk.tools.FunctionTool(func, require_confirmation)` | `require_confirmation` present |
| `ToolContext.request_confirmation(hint, payload)` | present, exactly those parameters |
| `Event.long_running_tool_ids` | present |
| `Runner.run_async(..., invocation_id=...)` | present (also `state_delta`, `yield_user_message`) |
| `REQUEST_CONFIRMATION_FUNCTION_CALL_NAME` | `= 'adk_request_confirmation'`, defined in `google/adk/flows/llm_flows/functions.py:60` |

**The blocker is cleared.** `InMemorySessionService` pickles cleanly both empty (137 bytes) and
**after holding a live session created through `create_session`** (426 bytes), with a successful
`pickle.loads` round trip. Since `GoogleADKSession` holds that service and is stored under the
framework key on the AK session (`adk.py:59-70`), **ADK pause state is durable through AK's
existing session store** on any configured backend. The ADK adapter's story stands as designed.

## Follow-up: ADK `App` break analysis

Run to answer open question 5 — what breaks if the adapter wraps agents in an `App` carrying
`ResumabilityConfig(is_resumable=True)`. Read from `google-adk` 2.8.0 source, not documentation.

| Finding | Detail |
|---|---|
| **AK already runs through an `App`** | `Runner.__init__` docstring: "Exactly one of `app`, `agent`, or `node` must be provided. When `agent` or `node` is provided, **the Runner wraps it into an `App` internally**. Providing `app` is the recommended way to create a runner." So passing `app=` is not a new concept — AK currently gets an implicit `App` with the default (non-resumable) config. |
| **Session key is preserved** | `Runner.__init__` body: `self.app_name = app_name or app.name`. Passing `app=App(name="AgentKernel", …)` with the existing `app_name="AgentKernel"` keeps `create_session(app_name="AgentKernel", …)` (`adk.py:190-195`) matching. |
| **Name-alignment check does not fire** | `Runner._enforce_app_name_alignment` only `logger.warning`s, and only when `_agent_origin_app_name` is set — i.e. the root agent was loaded from a directory implying a different app name. AK builds agents in code. |
| **One real behavioural change** | `runners.py:1772-1786`: with resumability on, a turn whose previous event was a function response is routed back to the agent that made the call; with it off, that routing is skipped. ADK's own comment defends the off behaviour as deliberate — "In non-resumable scenarios, a turn ending with function call response shouldn't trap the next turn on that same agent if it's not transferable." **For existing AK users with ADK sub-agents, which agent handles the next turn can change.** A trade-off, not a bug fix. |
| **Second-order cost** | `is_resumable` also gates agent-state event emission in `llm_agent.py:563`, `sequential_agent.py:87,105`, `parallel_agent.py:197,227`, `loop_agent.py:101,135` and `base_llm_flow.py:966,984`. Those events accumulate in the ADK session, which AK pickles into its session store, so ADK sessions grow for every user. |
| **Different invocation setup path** | `runners.py:1155-1175`: resumable runs take the `_resolve_invocation_id` branch instead of `_setup_context_for_new_invocation`, and only a resumable app may be run with no `new_message`. |

## Follow-up: retracting the "ADK streaming is documented unsupported" claim

An earlier draft of `design.md` stated that ADK streaming pause was "documented as unsupported",
citing upstream issues. That claim was sourced from **GitHub search-result titles, not from
reading the issues**, and it does not survive checking. Recorded here because a false claim that
reached the design is worth a permanent correction, not a silent edit.

**There is no upstream documentation saying streaming and resume are incompatible.** The
[ADK resume guide](https://raw.githubusercontent.com/google/adk-docs/main/docs/runtime/resume.md)
never mentions streaming, `run_live`, `RunConfig` or `StreamingMode`.

The cited issues, read directly:

| Issue | State | ADK version | Streaming involved? |
|---|---|---|---|
| [#5064](https://github.com/google/adk-python/issues/5064) — unresolved pause check + streaming id mismatch | **Closed** | 1.27.3 | yes |
| [#5349](https://github.com/google/adk-python/issues/5349) — sub-agent sequential LRO tools fail to resume | **Closed** | 1.27.0–1.30.0 | **no** |

Both closed, both against ADK 1.x rather than the pinned 2.8.0, and one has nothing to do with
streaming.

What **can** be stated, read from 2.8.0's installed source rather than inferred:

- **The pause check was partly addressed.** `base_llm_flow.py:966-978` now tests whether a
  function call was resolved by the following response (`fc_ids.issubset(fr_ids)`) — the fix
  #5064 asked for. But it carries ADK's own comment: *"This only checks the last 2 events… This is
  a known limitation of the current 2-event window."*
- **The partial/persisted id split is intact.** `populate_client_function_call_id`
  (`functions.py:245-246`) assigns an id only when one is absent, and
  `_finalize_model_response_event` runs for both partial and non-partial events
  (`base_llm_flow.py:1122`, `:1235`), while only non-partial events are persisted
  (`base_llm_flow.py:1130-1133`). So an id a client reads from a streamed partial event may never
  have been stored.
- **Neither mechanism has been observed failing at 2.8.0.** They are reasons to test, not
  evidence of breakage.

**Conclusion:** ADK streaming pause is *unverified*, not *unsupported*. Decide by test in the ADK
PR. If it fails, document it as AK's own finding against 2.8.0 with a reproducible case — never
as an upstream position.

## Follow-up: AG-UI native interrupt support

Run to answer open question 7, whose original premise ("AG-UI has no equivalent, so the event is
dropped") turned out to be wrong. Checked against **AK's pinned `ag-ui-protocol` 0.1.22**
(`ak-py/uv.lock`; the declared floor is `>=0.1.16`) — so **no dependency bump is required**.

| Symbol | Verified at 0.1.22 |
|---|---|
| `RunFinishedEvent.outcome` | present |
| `RunFinishedInterruptOutcome` | fields `type`, `interrupts` |
| `RunFinishedSuccessOutcome` | present |
| `Interrupt` | fields `id`, `reason`, `message`, `tool_call_id`, `response_schema`, `expires_at`, `metadata` |
| `RunAgentInput.resume` | present |
| `ResumeEntry` | fields `interrupt_id`, `payload`, `status` |
| `ResumeStatus` | `Literal["resolved", "cancelled"]` — **closed** |

Two type facts that shape the design, both read from the installed package rather than the prose:

- **`Interrupt.reason` is a plain `str`, not a `Literal`.** The documented values
  (`tool_call`, `input_required`, `confirmation`) are *core values* — routing hints — and the
  field accepts any string. This is why AK defines its own `PausedInterruption.kind` vocabulary
  and passes it through untranslated: matching the documented values buys nicer client-side
  routing, not freedom from a mapper, because no mapper was ever required.
- **`ResumeStatus` *is* closed** — `Literal["resolved", "cancelled"]`. So the outbound direction
  is free and the **return** direction is the constrained one. `resolved` means the human
  answered; `cancelled` means they abandoned it without answering. A boolean
  `ResumeDecision.approved` could not have expressed that difference — mapping
  `cancelled` to `approved=False` would conflate "the human said no" with "the human dismissed it
  without deciding", which the agent should report differently. **Resolved:** `ResumeDecision`
  carries `status: Literal["approved", "denied", "cancelled"]`, so the AG-UI value survives the
  boundary intact. Note this is the *inbound* direction, and it is the only closed enum in the
  AG-UI surface — the outbound `reason` is free-form, so the constraint runs one way only.

Protocol shape, from the AG-UI docs: a pause is a **terminal** outcome — the run ends with
`RunFinished` carrying `outcome.type == "interrupt"` and a non-empty `outcome.interrupts[]`. Any
`StateSnapshot` / `MessagesSnapshot` needed for resume must be emitted **before** that event. The
client resumes on the same `threadId` via `RunAgentInput.resume`, an array of
`{interruptId, status: "resolved" | "cancelled", payload?, metadata?}`, and **must address every
open interrupt** — partial resumes are not allowed. `Interrupt.reason`'s core values
(`tool_call`, `input_required`, `confirmation`) line up closely with AK's proposed
`PausedInterruption.kind`.

Consequence for the design: the work belongs in `AGUIRequestHandler._events`, which gains a third
terminal shape, **not** in `AGUIMapper.to_agui`.

## Corrections to the survey

Four claims taken from the documentation do not hold at the pinned versions, or are sharper than
the docs implied. `spec.md` uses the verified form.

1. **OpenAI: `@tool` is not a decorator at 0.20.0.** The current docs page presents `@tool` as the
   primary spelling, but in 0.20.0 `agents.tool` resolves to a **module**, not a callable. The
   decorator is `agents.function_tool`, and that is what carries `needs_approval`. The survey's
   open note about which spelling to use is settled: **`function_tool`**.
2. **OpenAI: `RunState.from_json`'s agent parameter is named `initial_agent`**, not `agent`, and
   the full signature is `(initial_agent, state_json, *, context_deserializer, context_override,
   strict_context)`. The design's "requires the original starting agent" claim holds; the keyword
   is `initial_agent`.
3. **LangGraph: do not import the `__interrupt__` constant.** `langgraph.constants.INTERRUPT` still
   resolves to `"__interrupt__"` but emits `LangGraphDeprecatedSinceV10` — it is private as of
   v1.0 and slated for removal in v2.0. `spec.md` uses the literal string `"__interrupt__"`.
4. **Pydantic AI's deferred types are dataclasses, not Pydantic models.** `DeferredToolRequests`,
   `DeferredToolResults`, `ToolApproved` and `ToolDenied` have no `model_fields`, so they cannot be
   round-tripped with `model_dump()`/`model_validate()`. This matters directly to the paused-run
   record: the Pydantic AI payload must be serialised some other way, or held as the dataclass
   itself and relied on to pickle.

## Reproducing

The probe script lives outside the repo (it installs packages the repo deliberately does not
depend on). To re-run it after a framework bump, recreate the venv above and re-check the symbol
list in the tables — in particular re-check correction 4, since a move to Pydantic models would
change the serialisation choice in `spec.md`.

> **Probe caveat worth keeping.** Two checks initially reported false failures because
> `hasattr(SomeDataclass, "field_with_default_factory")` is `False` on the class — the attribute
> only exists on instances. Any future verification of a dataclass-based API must enumerate
> `dataclasses.fields(...)` rather than use `hasattr`.

## Follow-up: does a framework report a stale pause?

Run against the repo venv (`ak-py/.venv`), which is behind the lock for three of the four:
`openai-agents` 0.19.0, `langgraph` 1.0.10, `pydantic-ai-slim` 2.13.0, `google-adk` 2.5.0.
Executed, not read from docs, except where noted.

The question: if an ordinary turn happens while a pause is pending, does the framework notice when
the pause is later resumed?

| Framework | Ordinary turn while paused | Resuming afterwards |
|---|---|---|
| **Pydantic AI** | **Refused.** `UserError: Cannot provide a new user prompt when the message history contains unprocessed tool calls.` | Cannot arise. Answering an already-answered pause is also refused: `UserError: Tool call results were provided, but the message history does not contain any unprocessed tool calls.` |
| **LangGraph** | **Sticky interrupt.** A new input on the same `thread_id` merges into state, re-enters the interrupted node and pauses again — `__interrupt__` present, `get_state().next` unchanged at `('ask',)`, `len(state.interrupts) == 1`. | Cannot go stale; a later `Command(resume=...)` completes the original interrupt normally |
| **OpenAI** | **Allowed** — the ordinary run returns a normal answer | **No signal.** `RunState.from_json` + `approve` + `Runner.run` returns a normal answer, `interruptions == []`. The snapshot is detached and has no notion of being current |
| **Google ADK** | not executed | **No validation found.** `long_running_tool_ids` appears only in event emission (`tools/base_tool.py:77`), A2A conversion (`a2a/converters/event_converter.py:183-189,308-332`) and logging plugins; nothing in `flows/llm_flows/functions.py` matches an incoming `function_response` id against outstanding calls. *Source read, not executed* |

Method note: OpenAI and Pydantic AI were driven with fake models (`agents.models.interface.Model`
subclass, and `pydantic_ai.models.function.FunctionModel`) so no network call was made. LangGraph
used `InMemorySaver` and a two-node graph.

**Consequence for the design.** The `ak.run_seq` staleness counter was removed: it was a generic
mechanism for a problem that exists on OpenAI, possibly ADK, and *not at all* on the other two —
where the framework either refuses the situation outright or makes it unreachable. It also showed
that the design's "a new prompt runs normally and keeps the pause" held only for OpenAI; Pydantic
AI raises and LangGraph re-pauses. Both are now recorded per adapter in `design.md`.

## Follow-up: can interruptions be answered one at a time?

Same venv and pins as the section above. Executed except where noted.

The design originally refused any resume that did not address every open interruption, justified
as "the frameworks cannot take a partial answer". That is false for three of the four.

| Framework | One at a time? | Evidence |
|---|---|---|
| **LangGraph** | **Yes** | two parallel nodes each calling `interrupt()`; `Command(resume={id_a: "yes-A"})` completed node A (state shows `A=yes-A`) and returned B as `__interrupt__`; a second `Command(resume={id_b: ...})` then completed the graph |
| **OpenAI** | **Yes** | two tools with `needs_approval`; `state.approve(interruptions[0])` then `Runner.run(agent, state)` returned `final_output is None` with `interruptions == ['email']` — it pauses again on the remainder |
| **Google ADK** | **Yes**, by construction | resume is a `FunctionResponse` per call id; no "all must be answered" check exists in `flows/llm_flows/functions.py`. *Source read, not executed* |
| **Pydantic AI** | **No** | `UserError: Tool call results need to be provided for all deferred tool calls. Expected: {'tc2', 'tc1'}, got: {'tc1'}` |

**AG-UI does not require it either.** `RunAgentInput.resume` is `Optional[List[ResumeEntry]]` and
`ResumeEntry` is `{interrupt_id, status, payload}` (read at `ag-ui-protocol` 0.1.20 in the venv;
the lock is 0.1.22). Nothing in the protocol types requires every open interrupt to be addressed
in one resume, so the earlier claim that it did is withdrawn.

**Consequence for the design.** Partial resume is now allowed and drops out of the failure-mode
list, which goes from five to four. A partial resume that leaves interruptions open simply pauses
again, reusing the existing "a resume can pause again" path. Pydantic AI is the single exception
and AK refuses there **before** calling the framework, naming the missing ids — otherwise its
clear `UserError` would be swallowed by the adapter's `except Exception`.

## Follow-up: two more claims that asserted a framework limit

Same venv and pins. Both were stated in the design as things the frameworks cannot do.

**"New content cannot travel with a decision."** False for three of the four.

| Framework | Prompt alongside a decision | Evidence | Native intent, or AK making it work? |
|---|---|---|---|
| **Pydantic AI** | **Allowed** | `run_sync("and also tell me the weather", message_history=hist, deferred_tool_results=DeferredToolResults(approvals={"tc1": True}))` returned a normal answer | **Native.** `prompt` is the documented way to send a user message, and the guard that blocks it (`Cannot provide a new user prompt when the message history contains unprocessed tool calls`) is lifted precisely by supplying the results — so the framework's own rule is "resolve the pending calls first" |
| **LangGraph** | **Mechanically allowed** | `Command` has an `update` field; `Command(resume="yes", update={"note": "NEW CONTENT"})` resumed the node *and* the node read the new value | **AK's mapping.** `update` means *update the graph state*; there is no "send a prompt with your resume" feature. AK would encode the prompt as a write to the `messages` channel, which is how its adapter already feeds the graph (`langgraph.py:412`) — consistent, but invented here |
| **Google ADK** | **Unknown** | a `Content` can hold a text part beside the `function_response`, so it is structurally possible | **Unverified.** Not executed; whether the flow handles a mixed `Content` is a guess |
| **OpenAI** | **Not possible** | `Runner.run`'s `input` is `str \| list[TResponseInputItem] \| RunState` — mutually exclusive | n/a |

**The third column is the load-bearing one.** Exactly one framework has a parameter meaning "a new
user prompt" that accepts it beside a decision. So supporting this would not be "stop blocking a
capability" — it would be building a behaviour, and owning its semantics on two adapters where the
framework has no opinion. `design.md` records the resulting `400` as a scope decision on that
basis.

**"A session can hold only one resumable run."** True for LangGraph, Pydantic AI and ADK, each of
which keeps a single thread or history. **False for OpenAI:** two `RunState` snapshots captured
from the same agent were serialised, restored, approved and run independently, returning
different answers. The single `ak.paused_run` record is therefore AK's uniformity choice on that
adapter, not a framework limit — worth knowing, because it is the one place the constraint could
be relaxed later without fighting an SDK.

## Follow-up: the answer channel, with a multiple-choice example

Same venv and pins. The scenario throughout: an agent must establish a refund reason, with three
options — `damaged`, `wrong_item`, `changed_mind`.

| Framework | structured answer (`payload`) | free text (`message`) |
|---|---|---|
| **LangGraph** | **Full** — `Command(resume=<any value>)`, and the value becomes what `interrupt()` returns inside the node, so single- and multi-select are native | **Full**, same channel |
| **Google ADK** | **Full** — `FunctionResponse.response` is an arbitrary dict; a confirmation takes `{"confirmed": bool, "payload": {...}}` | Full, inside that dict |
| **Pydantic AI** | **Full, on the deferred-call axis** — `DeferredToolResults(calls={id: <any value>})`; on the *approval* axis only `ToolApproved(override_args=dict)` | **Full** through the deferred result; on an approval, denial only (`ToolDenied(message=str)`) |
| **OpenAI** | **None** — `approve(item, always_approve=False)` takes no value at all | **Denial only** — `reject(item, *, rejection_message=str)`, delivered to the model as the gated call's `function_call_output` |

**Pydantic AI carries a structured answer in full**, which an earlier note got wrong by looking
only at the approval axis. A tool raising `CallDeferred` surfaces as
`DeferredToolRequests.calls`, the question rides in that tool's own arguments, and the human's
answer is supplied as the tool's **result**:

- paused with `calls=[('ask_user', 'q1')]`, args
  `{'question': 'Which refund reason?', 'options': ['damaged', 'wrong_item', 'changed_mind']}`
- `DeferredToolResults(calls={"q1": "damaged"})` → the model received the tool return `'damaged'`
- `DeferredToolResults(calls={"q1": ["damaged", "wrong_item"]})` → the model received
  `['damaged', 'wrong_item']`, so multi-select works unchanged

**OpenAI cannot express a multiple choice.** `approve(item, always_approve=False)` takes no value
parameter, so approval carries nothing. The only text channel is
`reject(item, *, rejection_message=...)`, and the SDK delivers it to the model as the gated
call's output — captured on the resumed turn as:

```
{'call_id': 'c1', 'output': 'The customer said damaged, not changed_mind.',
 'type': 'function_call_output'}
```

So the human's words reach the **model**, which then decides whether to re-call the tool with a
corrected argument. That is a suggestion costing a model round-trip, not a selection — worth
stating separately in the OpenAI adapter docs, because the two are easy to conflate.
