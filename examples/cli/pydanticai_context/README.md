# Agent Kernel — per-run framework context/state (Pydantic AI)

This demo shows how to carry a **framework-agnostic context/state object across turns** using Agent
Kernel's reserved `framework_context` session value, with an agent built on Pydantic AI.

A grocery shopping assistant keeps a **cart** in the framework context. Three tools run side by side,
and the pairing is the point of this example:

- `add_to_cart(ctx, item)` — **native Pydantic AI tool**; appends to `ctx.deps`
- `view_cart(ctx)` — **native Pydantic AI tool**; reads `ctx.deps`
- `get_delivery_estimate(city)` — **Agent Kernel tool** bound with `PydanticAIToolBuilder`; uses
  `ToolContext`, takes no `RunContext`, and never sees `deps`

The cart survives across turns even though each turn is a separate run — that persistence is the
feature.

## How it works

1. **Seeding.** A small `PreHook` (`SeedCartContextPreHook`) runs before the agent and seeds
   `{"cart": []}` on the first turn (when no context is set). No context means "no injection", so
   existing apps are unaffected; a caller-set dict — even an empty one — is injected and round-tripped.
   Seeding once before the first run is the recommended way to opt a session into carrying per-run
   state.

2. **Injection.** The `PydanticAIRunner` loads a deep copy of the context and passes it as the run's
   **`deps`** (`agent.run(..., deps=...)`, and `agent.run_stream(..., deps=...)` when streaming).
   `deps` is Pydantic AI's only caller-dependency slot and Agent Kernel owns it — previously no `deps=`
   was passed at all, so every agent received the `None` default. There is no way for application code
   to supply its own `deps`, so this injection cannot displace a caller value.

3. **Tools read/write it.** A tool whose first parameter is typed `RunContext` receives the run's deps
   and reads or mutates `ctx.deps` — the injected dict — **in place**. This applies to instruction
   functions and output validators too, anything taking a `RunContext`.

4. **Write-back.** After a **successful** run, Agent Kernel writes the (mutated) object back to the
   session. On a framework error or a client disconnect mid-stream, the previously stored context is
   left intact (write-back is atomic per turn). Fidelity is **full round-trip** here: every key
   survives, including ones a tool adds mid-run.

5. **Showing it on every reply.** A `PostHook` (`AppendCartPostHook`) appends a `Current cart: …` line
   to every reply. Post-hooks run *after* the runner has already written the context back, so the hook
   reads the up-to-date cart straight from the session — no need for the agent to call `view_cart`.
   This also shows the two sides of the same state: hooks reach it through the session, tools through
   `ctx.deps`.

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
yet both earlier items are still there because the context round-tripped across every turn.

## `RunContext` vs `ToolContext`

Both tool styles work on the same agent, and they reach different things:

| | Declared as | Reaches |
|---|---|---|
| Native Pydantic AI tool | `tools=[add_to_cart]`, first param `RunContext` | `ctx.deps` — the per-run framework context (and Pydantic AI's own run metadata) |
| Agent Kernel tool | `tools=PydanticAIToolBuilder.bind([get_delivery_estimate])` | `ToolContext.get()` — session, agent, requests; portable to every other framework |

Use the native style when a tool needs to read or write the per-run context, and the builder style for
tools you want to reuse unchanged on another framework.

## Reading the context outside a tool

A pre-hook or post-hook with the session in hand seeds or reads the context through the dedicated
accessors — no need to name the reserved key:

```python
session.set_framework_context({"cart": []})   # seed
cart = session.get_framework_context()        # read back
```

Do not write the context from inside a tool through `ToolContext.get().session`: the runner injected a
deep copy and replaces the stored value wholesale on success, so such a write is discarded. Write
through `ctx.deps` instead — that is the object Agent Kernel writes back.

## Constraints

- The context must be a **picklable `dict`** — sessions are persisted with `pickle`. A non-picklable
  value raises a descriptive `TypeError` naming the offending key/type. `set_framework_context()`
  rejects a non-`dict` outright.
- **`deps` is not validated at runtime.** Pydantic AI deliberately does not type-check `deps` against
  `deps_type`, so an agent declaring `deps_type=MyDeps` receives the context dict without error. A tool
  doing `ctx.deps.some_field` fails at tool-call time — as it already did against the previous
  `deps=None` default. This demo declares `deps_type=dict` to document what it actually receives.
- **`agent.override(deps=...)` wins.** Pydantic AI resolves an active override ahead of the `deps=`
  argument, so inside an override block the framework context never reaches your tools and the
  write-back stores the unmutated copy.
- Round-trip fidelity is **not uniform across frameworks**. Pydantic AI and OpenAI have **full**
  round-trip (shown here). ADK round-trips all keys except AK-internal ones; smolagents round-trips
  only pre-seeded keys; prebuilt LangGraph agents round-trip only declared state channels; **CrewAI
  does not support it** (a set context is ignored with a warning). To write portably across
  frameworks, pre-seed every key you intend to write. See the
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
