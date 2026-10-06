# MAF Context Demo

This demo shows how a Microsoft Agent Framework (MAF) agent can interact with the Agent Kernel framework context across turns.

It uses a `PreHook` to seed a cart context and two tools (`add_to_cart` and `view_cart`) to modify and read it using the native MAF context `FunctionInvocationContext` injected into the tool. It also shows a third tool `set_delivery_note` that writes a new context variable via the native handle. A `PostHook` appends the state to the agent reply.

## Context flow

1. The pre-hook seeds `{"cart": []}` on the first turn.
2. MAF tools read and update `ctx.session.state["ak_context"]`.
3. After a successful run, the adapter writes that context back to the Agent Kernel session.
4. The post-hook reads the stored context and appends `Current cart:` and, when set, `Delivery note:` lines.

Try adding milk, then eggs, then a delivery note, and finally asking what is in the cart. The tests follow these four ordered turns, matching the ADK context example, and check the post-hook's footer rather than the model's wording. The delivery-note test also verifies that a key not present in the initial context survives across turns.

## Setup

You will need an `OPENAI_API_KEY` in your environment to run the demo and the tests.

```sh
./build.sh
```

To run the tests:

```sh
uv run pytest -s
```

## Run

```sh
uv run python demo.py
```
