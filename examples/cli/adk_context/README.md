# Agent Kernel — per-run framework context/state (Google ADK)

This demo shows how to carry a **framework-agnostic context/state object across turns** using Agent
Kernel's reserved `framework_context` session key, with an agent built on Google ADK.

A grocery shopping assistant keeps a **cart** in `framework_context`. Three tools operate on it
through ADK's native session state:

- `add_to_cart(item)` — appends an item to the cart
- `view_cart()` — returns the cart's current contents
- `set_delivery_note(note)` — writes a key that was **never seeded**, to show that keys a tool adds
  mid-run survive on ADK

## Why this matters on ADK

ADK keeps its state in an `InMemorySessionService`, which is **not** part of the pickled Agent Kernel
session. Without the `framework_context` round-trip, anything your tools put in ADK state is lost as
soon as the process goes away. The write-back copies that state into a durable session key, so the
cart is reloaded on the next turn by whatever session store you have configured.

The post-hook in this demo deliberately reads `session.get(framework_context)` — the Agent Kernel
session, not ADK's state. Everything it prints is therefore proof that the round-trip happened.

## How it works

1. **Seeding.** A small `PreHook` (`SeedCartContextPreHook`) runs before the agent and seeds
   `framework_context = {"cart": []}` on the first turn (when the key is absent). An absent key means
   "no context / no injection", so existing apps are unaffected; a caller-set dict — even an empty
   one — is injected and round-tripped.

2. **Injection.** The `GoogleADKRunner` loads a deep copy of `framework_context` and merges its keys
   into the ADK session `state` for the run. Agent Kernel's own internal key (`ak_tool_context`) is
   written last, so a caller key can never displace it.

3. **Tools read/write it.** Each tool declares a `tool_context: ToolContext` parameter — ADK injects
   it — and reads or writes `tool_context.state`. Note the tools **assign** back
   (`tool_context.state["cart"] = cart`) rather than mutating a list in place: ADK records a state
   delta on assignment, and only what lands in the state is read back.

4. **Write-back.** After a **successful** run, Agent Kernel reads the accumulated ADK state back and
   writes it to the session key. On a framework error or a client disconnect mid-stream, the
   previously stored context is left intact (write-back is atomic per turn).

5. **Showing it on every reply.** A `PostHook` (`AppendCartPostHook`) appends `Current cart: …` (and
   `Delivery note: …` once set) to every reply, read from the session key.

## Bound tools vs. direct tools

The tools here are passed to the ADK agent **directly** (`tools=[add_to_cart, …]`), not through
`GoogleADKToolBuilder.bind`. The builder wraps a function so that Agent Kernel's `ToolContext` is set
for the call — it consumes the `tool_context` argument and does not forward it, so a bound tool
cannot reach ADK state.

| You need | Pass the tool |
|---|---|
| ADK state (`tool_context.state`) — the per-run context | directly, declaring `tool_context: ToolContext` |
| Agent Kernel's `ToolContext.get()` — session, runtime, agent | through `GoogleADKToolBuilder.bind([...])` |

## Example session

```
(shopping) >> Add milk to my cart.
Added 'milk'. The cart now has 1 item(s).

Current cart: milk
(shopping) >> Add eggs as well.
Added 'eggs'. The cart now has 2 item(s).

Current cart: milk, eggs
(shopping) >> Leave the order at the front door.
Noted: leave at the front door

Current cart: milk, eggs
Delivery note: leave at the front door
(shopping) >> What's in my cart right now?
The cart contains: milk, eggs

Current cart: milk, eggs
Delivery note: leave at the front door
```

`delivery_note` was never seeded — the tool added it mid-run, and ADK's full read-back carried it
into the session. On smolagents the same write would be silently dropped, because there the
read-back is restricted to keys you pre-seeded.

## ADK-specific caveats

Because the whole (stripped) ADK state is read back, two things follow:

- **The state is accumulate-only.** ADK keeps every key written to a session for that session's
  lifetime, so deleting a key from `framework_context` does not remove it — it reappears on the next
  write-back. Clear a value by overwriting it (`None`, `[]`), not by deleting the key.
- **Agent-written state round-trips too.** A value the agent writes itself — most commonly
  `LlmAgent(output_key="...")`, which stores the agent's response in the state — is indistinguishable
  from a tool write, so it also lands in `framework_context`.

Agent Kernel strips its own `ak_tool_context` key plus ADK's `app:`/`user:`/`temp:`-prefixed entries
(app- and user-scoped values ADK merges in on read, and invocation-scoped scratch) before storing, so
those never enter the caller's context.

## Reading the context outside a tool

Any code with the session in hand can seed or read the context via the enum member (not the raw
string):

```python
from agentkernel.core import Session

session.set(Session.Keys.FRAMEWORK_CONTEXT.value, {"cart": []})   # seed
cart = session.get(Session.Keys.FRAMEWORK_CONTEXT.value)          # read back
```

Do **not** write to it from inside a tool via `ToolContext.get().session`: on ADK the runner replaces
the key wholesale with the state it reads back, so a session-side write from a tool is discarded.
Write through `tool_context.state`, or from application code / a post-hook that runs after the runner.

## Constraints

- `framework_context` must be a **picklable `dict`** — sessions are persisted with `pickle`. A
  non-`dict` value, or a non-picklable one, raises a descriptive `TypeError` naming the offending
  key/type.
- Round-trip fidelity is **not uniform across frameworks**. ADK round-trips all keys except
  AK-internal and scope-prefixed ones (shown here). OpenAI has full round-trip; smolagents round-trips
  only pre-seeded keys; prebuilt LangGraph agents round-trip only declared state channels; **CrewAI
  does not support it** (a set context is ignored with a warning). To write portably across
  frameworks, pre-seed every key you intend to write. See the
  [Runner docs](https://github.com/yaalalabs/agent-kernel/blob/develop/docs/docs/core-concepts/runner.md)
  for the full fidelity table.

## Running

This demo uses `LiteLlm(model="openai/gpt-4o-mini")`, so set `OPENAI_API_KEY` in your environment.

Install dependencies:

    ./build.sh

Install local `agentkernel` in development mode:

    ./build.sh local

Run the demo:

    python demo.py

Run the tests:

    uv run pytest -s
