# Agent Kernel — Claude per-run context example

This grocery assistant keeps a cart across turns using Agent Kernel's `framework_context`.
Its Python tools read the current run's cart with `ToolContext.get().framework_context`.

## How it works

1. `SeedCartContextPreHook` creates `{"cart": []}` before the first run.
2. The Claude runner copies that dictionary for the run. The tools change the copy through
   `ToolContext.get().framework_context`.
3. After a successful run, the runner saves the updated dictionary in the Agent Kernel session.
4. `AppendCartPostHook` reads the saved cart and adds a `Current cart:` line to the reply.

For example, ask to add milk, then eggs, then ask what is in the cart. The third turn can still
see both items:

```text
(shopping) >> Add milk to my cart.
Added 'milk'.

Current cart: milk
(shopping) >> Add eggs too.
Added 'eggs'.

Current cart: milk, eggs
(shopping) >> What's in my cart?
The cart contains: milk, eggs

Current cart: milk, eggs
```

Claude's SDK tool handlers receive tool arguments, but no native run-context object. This example
uses `ToolContext.framework_context` for Agent Kernel-bound Python tools. Claude's built-in tools and external
MCP servers cannot read it.

## Run

Set up Claude Agent SDK authentication with an Anthropic API key or a configured Bedrock or Vertex
provider. Then install and run:

```bash
./build.sh local  # use a locally built agentkernel wheel
python demo.py
```

Use `./build.sh` to install a published `agentkernel` package that includes the `claude` extra.
The example keeps Claude Code's built-in tools and local settings disabled; it allows only the two
bound cart tools.
