# Human in the loop — pause for approval, then resume

An agent that stops before it does something consequential, waits for a person to decide, and
carries on from that decision.

The whole setup is one argument:

```python
@function_tool(needs_approval=True)
def issue_refund(order_id: str) -> str:
    ...
```

The OpenAI Agents SDK stops before running the tool and hands the pending call back. Agent Kernel
turns that into a **paused reply**, stores what it needs to continue, and answers the client with
HTTP `202`.

## Run it

```bash
./build.sh
export OPENAI_API_KEY=sk-...
uv run app.py
```

Two surfaces are mounted, and the same pause can be answered from either:

| | |
|---|---|
| `POST /agui/support` | AG-UI — streamed, ends with an **interrupt outcome** |
| `POST /api/v1/chat` | REST — answers **202** with `status: "PAUSED"` |

## The approval console

A small React app that makes the pause visible. From `frontend/`:

```bash
npm install
npm run dev          # http://localhost:5173, proxies /agui to this process
```

Or `npm run build`, and `app.py` then serves it at `http://localhost:8000/`.

Ask it to refund `ORD-1001`. The agent looks the order up, then stops — and instead of an answer you
get a card showing **the tool it wants to call and the arguments it wants to call it with**, because
nobody can approve a call they cannot see. Three buttons: Approve, Deny with a reason, Cancel.

Under the hood the run ended with AG-UI's third terminal shape:

```json
{ "type": "RUN_FINISHED",
  "outcome": { "type": "interrupt",
               "interrupts": [ { "id": "call_abc123", "reason": "tool_call",
                                 "metadata": { "tool_name": "issue_refund",
                                               "arguments": "{\"order_id\": \"ORD-1001\"}" } } ] } }
```

A pause is the run's **outcome**, not an error and not a mid-stream event — which is why the stream
still closes cleanly and the client branches on `outcome` rather than watching for a failure.

Pressing a button sends the next run with a `resume` block:

```json
{ "resume": [ { "interruptId": "call_abc123", "status": "resolved", "payload": true } ] }
```

The protocol carries two statuses where Agent Kernel carries three. `cancelled` is its own status,
so "nobody decided" never reaches the model as a refusal; approve and deny are both `resolved`, told
apart by a boolean payload — which is just the answer to "may I?".

There is deliberately nowhere to say *why* something was refused. AG-UI has no field for it, and
Agent Kernel does not reserve keys inside `payload` to smuggle one: the SDK states that `payload` is
"the answer the agent asked for", so squatting there would both contradict the protocol and swallow a
real answer that happened to use the same key. If you need the human's words to reach the model, use
the REST surface above, where `message` is a field of its own.

## The three-step exchange

**1. Ask for something gated.**

```bash
curl -s localhost:8000/api/v1/chat -H 'content-type: application/json' -d '{
  "session_id": "demo-1", "agent": "support",
  "prompt": "Please refund order ORD-1001."
}'
```

The run does not finish. You get `202` and a body that says why:

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

`status: "PAUSED"` is the top-level discriminator, so a client branches on the outcome without
parsing `result`. The `arguments` are there because a human cannot approve a call they cannot see.

**2. Send the decision.** No prompt — this turn *is* the answer.

```bash
curl -s localhost:8000/api/v1/chat -H 'content-type: application/json' -d '{
  "session_id": "demo-1", "agent": "support",
  "resume": { "decisions": [ { "id": "call_abc123", "status": "approved" } ] }
}'
```

**3. The run continues** and the tool finally executes.

### Denying, and the difference from cancelling

```json
{ "id": "call_abc123", "status": "denied", "message": "Outside the 30-day refund window." }
```

`status` is three-valued on purpose:

| | meaning | what the model is told |
|---|---|---|
| `approved` | do it | the tool runs |
| `denied` | a person said no | your `message`, so the model can explain the refusal |
| `cancelled` | nobody decided — it timed out, or the UI was closed | Agent Kernel's own wording, which reads as *undecided*, not refused |

A boolean would collapse the last two, and the agent would report a refusal that never happened.

## The one thing to get right in production

A pause lives on the **session**, and a human answers minutes or hours later — after a restart, and
often on a different replica. `config.yaml` here uses `in_memory`, which keeps the session in one
process and is fine for a demo:

```yaml
session:
  type: redis          # or valkey, dynamodb, cosmosdb, firestore
  redis:
    url: "redis://localhost:6379"
```

Agent Kernel logs a `WARNING` the first time a pause is written while `type: in_memory`, naming this
exact problem. Take it seriously — without a shared backend the decision arrives at a replica that
has never heard of the pause.

## Run the tests

```bash
uv run pytest -s
```

They drive the full exchange: the gated tool pausing, an approval running it, a denial *not* running
it, and an ungated tool still answering in one turn.

## Two agents, because the frameworks differ

The example runs **two**, and the difference between them is the most useful thing here.

| | `support` (OpenAI) | `planner` (LangGraph) |
|---|---|---|
| Pauses on | a tool declared `needs_approval=True` | a node calling `interrupt()` |
| Interruption kind | `tool_call` | `input_required` |
| The human can | approve or deny | **choose an option, or type an answer** |

### Why OpenAI cannot ask a question

The OpenAI Agents SDK records an approval as a **boolean** — `RunState.approve()` takes no value —
so there is nowhere in its resume path for "the human chose Store credit". Agent Kernel refuses a
`payload` on that adapter rather than dropping it silently:

> The OpenAI adapter cannot deliver a structured answer … `RunState.approve()` takes no value.

The OpenAI-shaped way to offer a choice is for the model to **propose** one in the tool arguments
and the human to approve or deny it — deny, and the model proposes another.

### What LangGraph can do

`interrupt()` returns whatever the resume supplies, so the answer *is* the value:

```bash
# a choice
curl -s localhost:8000/api/v1/chat -H 'content-type: application/json' -d '{
  "session_id": "demo-2", "agent": "planner",
  "resume": { "decisions": [ { "id": "<interrupt id>", "payload": "Store credit" } ] } }'

# free text, the very next turn
... "payload": "Apologise for the delay." ...
```

The `planner` node asks **two** questions in a row. The second is reached only once the first has an
answer, so the run pauses twice and you answer one at a time — which is also the case that exercises
Agent Kernel's checkpointer, since the pause has to survive between turns.

Two things worth knowing, both LangGraph's behaviour rather than Agent Kernel's:

- **The node re-runs from the top** on resume. The first `interrupt()` then returns the stored
  answer instead of pausing again — so anything with a side effect belongs *after* the questions.
- **A node that returns a message without calling a model streams nothing.** `astream_events`
  streams model tokens, so the graph ends with a small model call to write the confirmation. Over
  REST the text would come back either way, which makes this an easy asymmetry to miss.

## What else is possible

- **Streaming.** With `execution.mode: stream`, the pause arrives as a `run_paused` event and the
  stream ends normally rather than with an error — a pause is an outcome, not a failure.
- **The other two frameworks.** Pydantic AI pauses on both `CallDeferred` and `requires_approval`,
  and Google ADK on long-running tools and confirmations. Like LangGraph, both carry a structured
  answer back; OpenAI and ADK reject a prompt sent alongside a decision, and say so.
- **AG-UI.** A pause ends the run with an interrupt outcome, and the client resumes with
  `RunAgentInput.resume`.
