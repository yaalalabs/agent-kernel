---
sidebar_position: 4.5
---

# Human in the Loop

Some things an agent proposes should not happen until a person says so. Agent Kernel lets a run
**pause**, hands the question back to your client, and continues from the answer — minutes or hours
later, on whichever replica receives it.

A pause is a normal outcome, not an error. The run stops cleanly, the client is told what is being
asked, and nothing has happened yet.

## Turning it on

There is no `enabled` flag. A pause happens when the **framework** decides one is needed, so you
declare it where the framework does:

```python
from agents import function_tool

@function_tool(needs_approval=True)          # OpenAI Agents SDK
def issue_refund(order_id: str) -> str:
    ...
```

```python
from langgraph.types import interrupt        # LangGraph

def ask(state):
    choice = interrupt({"question": "Which method?", "options": ["Card", "Credit"]})
    ...
```

Four frameworks can pause: **OpenAI Agents SDK**, **LangGraph**, **Pydantic AI** and **Google ADK**.
CrewAI and smolagents cannot, and say so rather than pretending — their runners report
`supports_pause = False`.

## What a paused run looks like

The request answers **HTTP 202** with a top-level discriminator, so a client branches on the outcome
without parsing `result`:

```json
{
  "status": "PAUSED",
  "run_id": "9f2c…",
  "agent": "support",
  "interruptions": [
    { "id": "call_abc123", "kind": "tool_call", "tool_name": "issue_refund",
      "arguments": "{\"order_id\": \"ORD-1001\"}" }
  ],
  "session_id": "demo-1"
}
```

`agent` is there because a resume must name the agent that paused — see
[Answering it](#answering-it). `arguments` is there because nobody can approve a call they cannot
see.

`kind` says what is being asked:

| `kind` | Meaning |
|---|---|
| `tool_call` | a gated tool wants permission |
| `confirmation` | the framework is asking for a yes or no of its own |
| `input_required` | the agent wants a **value** — a choice, or free text |

## Answering it

Send the decisions instead of a prompt. The request needs no `prompt` at all:

```json
{
  "session_id": "demo-1",
  "agent": "support",
  "resume": { "decisions": [ { "id": "call_abc123", "status": "approved" } ] }
}
```

A decision carries up to three things:

| Field | For |
|---|---|
| `status` | `approved`, `denied` or `cancelled` |
| `message` | the human's own words — a free-text answer, or the reason for a refusal |
| `payload` | a structured answer: the option chosen, overridden arguments. **Any JSON value**, not just an object |

`status` is required for `tool_call` and `confirmation`, and ignored for `input_required` — a
question asking for a value has nothing to approve.

### Why `cancelled` is not `denied`

`denied` means a person said no. `cancelled` means **nobody decided** — a timeout, a closed tab, a
shift ending. Only LangGraph carries that distinction natively; on the others Agent Kernel supplies
wording that reads as *undecided* rather than refused, so the agent does not report a refusal that
never happened.

A boolean would collapse the two, and the model would confidently tell your customer they were
turned down.

### Answering one question at a time

A pause can hold several interruptions. You may answer some now and the rest later — the remainder
comes back as another paused reply with a fresh `run_id`. Pydantic AI is the exception: it requires
every deferred call resolved together, and Agent Kernel refuses a partial resume **before** calling
it, naming the ids you missed.

## Durability: the one thing to get right

A pause is written into the **session**, and the answer arrives later — after a restart, often on a
different replica. Agent Kernel stores it under a framework-owned key (`ak.paused_runs`) in the
session's non-volatile cache.

```yaml
session:
  type: redis          # or valkey, dynamodb, cosmosdb, firestore
  redis:
    url: "redis://localhost:6379"
```

With `type: in_memory` the record lives in one process. That is fine for local development and
**wrong for anything multi-replica**: the replica receiving the decision has never heard of the
pause. Agent Kernel logs a `WARNING` the first time a pause is written that way, naming this exact
problem.

Three limits worth knowing, none of them hidden:

- **Answer it soon or lose it.** Expiry rides the session store's own TTL. There is no separate
  pause TTL.
- **Clearing the non-volatile cache discards pending decisions.** That cache is application space;
  the `ak.` prefix marks the key as framework-owned, but nothing stops an application clearing it.
- **Two replicas writing a pause at the same moment can lose one.** Writing the record is a
  read-modify-write over the session, and the session lock is per process. This is a property of the
  non-volatile cache generally, not of pausing — but here the entry lost is a human's pending
  decision.

## What each framework can carry back

The frameworks genuinely differ, and Agent Kernel does not paper over it. A rejection is raised
where it can still reach you, rather than being flattened into "something went wrong".

| | OpenAI | LangGraph | Pydantic AI | Google ADK |
|---|---|---|---|---|
| A structured `payload` | **rejected** | yes | yes | yes |
| A `prompt` beside a decision | **rejected** | yes | yes | **rejected** |
| A second pause in one session | **appends** | replaces | replaces | replaces |
| Detects a stale resume | **no** | n/a — re-pauses | yes, refuses | no |

**OpenAI cannot ask a question.** An approval is recorded as a boolean — `RunState.approve()` takes
no value — so a gated tool can only be approved or denied. To offer a choice there, have the model
**propose** one in the tool arguments; deny, and it proposes another. If you need a value, ask for
it as an ordinary conversational turn rather than a gated tool.

**A stale resume on OpenAI is not detected.** Pause, run an ordinary turn, then answer the old
pause, and you get a confident answer computed as though the intervening turns never happened. Agent
Kernel does not track this and neither does the SDK. Answer a pause before continuing the
conversation.

**LangGraph re-runs the interrupting node from the top** on resume. The first `interrupt()` then
returns the stored answer instead of pausing again — so any side effect must sit *after* the
questions, not before them. Agent Kernel also assigns its own checkpointer, overwriting one you
supplied.

**Google ADK** enables `ResumabilityConfig(is_resumable=True)` on every run. Two consequences:
a turn following a function response is routed back to the agent that made the call, which can
change which agent handles the next turn in a multi-agent app; and ADK sessions grow, because that
setting also gates agent-state event emission. ADK's own note applies too — a tool may run more than
once when resuming.

## Streaming

With `execution.mode: stream` a pause arrives as a `run_paused` event and the stream ends
**normally** — never through `StreamChunk.error`. Any open boundary (a tool call, a message) is
closed first, so a frontend does not render the gated call as work still in progress forever.

## Over AG-UI

A pause is the run's terminal outcome:

```json
{ "type": "RUN_FINISHED",
  "outcome": { "type": "interrupt", "interrupts": [ { "id": "call_abc123", "reason": "tool_call" } ] } }
```

Resume with `RunAgentInput.resume`. Two protocol limits apply: `ResumeEntry.status` carries two
values, so approve and deny are a boolean `payload`; and there is no field for a refusal's wording or
for a prompt sent beside a decision. Agent Kernel does not invent a private encoding for either —
use the REST surface when you need them. See [AG-UI Server](../api/agui-server.md).

## A runnable example

[`examples/api/hitl/`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/api/hitl) runs
two agents side by side — an OpenAI one that can only be approved or denied, and a LangGraph one that
asks a multiple-choice question and then a free-text one — with a small React console for answering
them.
