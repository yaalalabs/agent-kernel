# Agent Kernel — per-run framework context/state (OpenAI Agents SDK)

This demo shows how to carry a **framework-agnostic context/state object across turns** using Agent
Kernel's reserved `framework_context` session key, with an agent built on the OpenAI Agents SDK.

A grocery shopping assistant keeps a **cart** in `framework_context`. Two tools operate on it:

- `add_to_cart(item)` — appends an item to the cart
- `view_cart()` — returns the cart's current contents

The cart survives across turns even though each turn is a separate run — that persistence is the
feature.

## How it works

1. **Seeding.** A small `PreHook` (`SeedCartContextPreHook`) runs before the agent and seeds
   `framework_context = {"cart": []}` on the first turn (when the key is absent). An absent key means
   "no context / no injection", so existing apps are unaffected; a caller-set dict — even an empty
   one — is injected and round-tripped. Seeding once before the first run is the recommended way to
   opt a session into carrying per-run state.

2. **Injection.** The `OpenAIRunner` loads a deep copy of `framework_context` and passes it as the
   OpenAI Agents SDK run **context** (`Runner.run(..., context=...)`).

3. **Tools read/write it.** Each tool declares a first parameter typed `RunContextWrapper` and reads
   or mutates `ctx.context` — the injected dict — **in place**.

4. **Write-back.** After a **successful** run, Agent Kernel writes the (mutated) object back to the
   same session key. On a framework error or a client disconnect mid-stream, the previously stored
   context is left intact (write-back is atomic per turn).

5. **Showing it on every reply.** A `PostHook` (`AppendCartPostHook`) appends a `Current cart: …`
   line to every reply. Post-hooks run *after* the runner has already written the context back, so
   the hook reads the up-to-date cart straight from `session.get(framework_context)` — no need for
   the agent to call `view_cart`. This also shows that the same per-run state is reachable from a
   hook (via the session) as from a tool (via the run context).

The context is a normal durable session key, so it is persisted by the configured session store and
reloaded on the next turn — no extra plumbing.

## Example session

```
(shopping) >> Add milk to my cart.
Added 'milk'. The cart now has 1 item(s).

Current cart: milk
(shopping) >> Add eggs as well.
Added 'eggs'. The cart now has 2 item(s).

Current cart: milk, eggs
(shopping) >> What's in my cart right now?
The cart contains: milk, eggs

Current cart: milk, eggs
```

The `Current cart:` line is appended by the post-hook on every turn. The third turn is a fresh run,
yet both earlier items are still there because `framework_context` round-tripped across every turn.

## Reading the context outside a tool

Any code with the session in hand can seed or read the context via the enum member (not the raw
string):

```python
from agentkernel.core import Session

session.set(Session.Keys.FRAMEWORK_CONTEXT.value, {"cart": []})   # seed
cart = session.get(Session.Keys.FRAMEWORK_CONTEXT.value)          # read back
```

A tool that is not written against a specific framework can also reach the stored value through
`ToolContext.get().session`. Note, however, that on OpenAI a tool's *mutations* only round-trip when
they are made on `RunContextWrapper.context` (the injected object) — that is the object Agent Kernel
writes back.

## Constraints

- `framework_context` must be a **picklable `dict`** — sessions are persisted with `pickle`. A
  non-picklable value raises a descriptive `TypeError` naming the offending key/type.
- Round-trip fidelity is **not uniform across frameworks**. OpenAI has **full** round-trip (shown
  here). ADK round-trips all keys except AK-internal ones; smolagents round-trips only pre-seeded
  keys; prebuilt LangGraph agents round-trip only declared state channels; **CrewAI does not support
  it** (a set context is ignored with a warning). To write portably across frameworks, pre-seed
  every key you intend to write. See the
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
