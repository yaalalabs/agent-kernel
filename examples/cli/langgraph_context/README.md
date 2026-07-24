# Agent Kernel — per-run framework context/state (LangGraph)

This demo shows how to carry a **framework-agnostic context/state object across turns** using Agent
Kernel's reserved `framework_context` session key, with an agent built on LangGraph.

A grocery shopping assistant keeps a **cart** in `framework_context`. A custom LangGraph
`StateGraph` declares a `cart` channel in its state schema; a single node reads the cart, applies the
user's request, and writes the updated cart back onto that channel. The cart survives across turns
even though each turn is a separate run — that persistence is the feature.

## Why a *custom* graph (and not `create_react_agent`)

LangGraph is the one framework where round-trip fidelity depends on **your graph's state schema**.
Agent Kernel spreads the `framework_context` dict's top-level keys into the graph input, but only
reads back the keys the graph **declares as state channels**:

```python
class ShoppingState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    cart: list[str]          # <-- declared channel → round-trips
```

A prebuilt `create_react_agent` uses a fixed `AgentState` (`messages`, `remaining_steps`,
`structured_response`) and **silently drops unknown keys**. If you seeded `cart` there, it would be
injected on the way in but never come back on the way out — so it would not persist. Declaring the
`cart` channel, as this demo does, is what makes the round-trip real.

> `framework_context` is also **distinct from LangGraph's own checkpointed state**. This demo reads
> and writes the cart through `session.get(framework_context)` — the framework-agnostic, caller-facing
> slot — not through LangGraph's internal checkpointer. That is what lets a plain `PreHook`/`PostHook`
> (and any tool, on any framework) touch the same state with identical code.

## How it works

1. **Seeding.** A small `PreHook` (`SeedCartContextPreHook`) runs before the agent and seeds
   `framework_context = {"cart": []}` on the first turn (when the key is absent). An absent key means
   "no context / no injection", so existing apps are unaffected; a caller-set dict — even an empty
   one — is injected and round-tripped. Seeding once before the first run is the recommended way to
   opt a session into carrying per-run state.

2. **Injection.** The `LangGraphRunner` loads a deep copy of `framework_context` and spreads its
   top-level keys into the graph input alongside `messages` (`input={"messages": …, "cart": …}`).
   `messages` is written last, so a caller key can never overwrite the conversation.

3. **The graph reads/writes it.** The `shopping` node reads `state["cart"]`, appends the requested
   items, and returns an updated `cart` on the declared channel.

4. **Write-back.** After a **successful** run, Agent Kernel reads back the keys the schema declared
   (`cart`) and writes them to the same session key. On a framework error or a client disconnect
   mid-stream, the previously stored context is left intact (write-back is atomic per turn).

5. **Showing it on every reply.** A `PostHook` (`AppendCartPostHook`) appends a `Current cart: …`
   line to every reply. Post-hooks run *after* the runner has already written the context back, so
   the hook reads the up-to-date cart straight from `session.get(framework_context)`. This shows that
   the same per-run state is reachable from a hook (via the session) as from inside the graph (via
   the state channel).

The context is a normal durable session key, so it is persisted by the configured session store and
reloaded on the next turn — no extra plumbing.

## Example session

```
(shopping) >> Add milk to my cart.
Added milk to your cart.

Current cart: milk
(shopping) >> Add eggs as well.
Added eggs to your cart.

Current cart: milk, eggs
(shopping) >> What's in my cart right now?
Your cart has milk and eggs.

Current cart: milk, eggs
```

The `Current cart:` line is appended by the post-hook on every turn. The third turn is a fresh run,
yet both earlier items are still there because `framework_context` round-tripped across every turn
via the declared `cart` channel.

## Reading the context outside the graph

Any code with the session in hand can seed or read the context via the enum member (not the raw
string):

```python
from agentkernel.core import Session

session.set(Session.Keys.FRAMEWORK_CONTEXT.value, {"cart": []})   # seed
cart = session.get(Session.Keys.FRAMEWORK_CONTEXT.value)          # read back
```

A tool can also reach the stored value through `ToolContext.get().session`. On LangGraph, remember
that a value only *round-trips* if the graph's state schema declares it as a channel; other keys are
injected but dropped on the way out.

## Constraints

- `framework_context` must be a **picklable `dict`** — sessions are persisted with `pickle`. A
  non-picklable value raises a descriptive `TypeError` naming the offending key/type.
- Round-trip fidelity is **not uniform across frameworks**. LangGraph round-trips only **declared
  state channels** (shown here). OpenAI has full round-trip; ADK round-trips all keys except
  AK-internal ones; smolagents round-trips only pre-seeded keys; **CrewAI does not support it** (a
  set context is ignored with a warning). To write portably across frameworks, pre-seed every key
  you intend to write. See the
  [Runner docs](https://github.com/yaalalabs/agent-kernel/blob/develop/docs/docs/core-concepts/runner.md)
  for the full fidelity table.

## Running

Install dependencies:

    ./build.sh

Install local `agentkernel` in development mode:

    ./build.sh local

Run the demo:

    python demo.py

Run the tests:

    uv run pytest -s
