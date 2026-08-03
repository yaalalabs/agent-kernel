# Agent Kernel — per-run framework context/state (OpenAI Agents SDK)

This demo shows how to carry a **framework-agnostic context/state object across turns** using Agent
Kernel's reserved `framework_context` session key, with an agent built on the OpenAI Agents SDK.

A grocery shopping assistant keeps a **cart** in `framework_context`. Two tools operate on it, and
each is declared in a **different but equally supported style**:

- `add_to_cart(ctx, item)` — appends an item to the cart; declared the **framework-recommended** way,
  decorated with the OpenAI Agents SDK's own `@function_tool` and passed straight into `tools=`
- `view_cart(ctx)` — returns the cart's current contents; declared the **Agent Kernel** way, left as a
  plain function and bound with `OpenAIToolBuilder.bind`

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
   or mutates `ctx.context` — the injected dict — **in place**. This works in either declaration
   style: `OpenAIToolBuilder.bind` applies `function_tool` for you, so a bound tool sees the run
   context exactly as a hand-decorated one does.

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

## Two ways to declare a tool

Both styles work on the same agent and compose in a single `tools=` list:

```python
tools=[add_to_cart] + OpenAIToolBuilder.bind([view_cart])
```

| | Declared as | Notes |
|---|---|---|
| Framework-recommended | `@function_tool` on the function, then `tools=[add_to_cart]` | Use the SDK directly; full access to `function_tool`'s own options (custom name, description override, failure handler) |
| Agent Kernel | plain function, then `tools=OpenAIToolBuilder.bind([view_cart])` | The builder calls `function_tool` for you; the same function body can be bound to another framework's builder unchanged |

Neither style changes how the per-run context is reached — a `RunContextWrapper` first parameter is
honoured in both. Reach for the builder when you want the tool to stay portable across frameworks,
and for the decorator when you need SDK-specific tool options.

## Reading the context outside a tool

A pre-hook or post-hook with the session in hand seeds or reads the context through the dedicated
accessors — no need to name the reserved key:

```python
session.set_framework_context({"cart": []})   # seed
cart = session.get_framework_context()        # read back
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
