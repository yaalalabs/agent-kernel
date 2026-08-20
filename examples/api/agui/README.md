# Agent Kernel over the AG-UI protocol

This package contains a demo of an Agent Kernel agent driven over [AG-UI](https://github.com/ag-ui-protocol/ag-ui),
an event-based protocol for talking to a user-facing frontend. The app mounts `AGUIRequestHandler`
(see `app.py`), which is what enables the AG-UI surface; the `agui` block in `config.yaml` only
parameterizes it.

The agent is an OpenAI Agents SDK agent that keeps a short task list in AG-UI's **shared state**. That
list is the point of the demo: the model amends it by calling `update_agui_state`, the server streams
the amended copy back as a `StateSnapshot`, the browser renders it in the right-hand panel, and the
browser echoes it on the next run. Neither side owns the list; both read and write it.

`frontend/` is a small **React + TypeScript** app (Vite), built to `frontend/dist` and served by `app.py` at
`GET /` — the same origin as the AG-UI routes, so the browser needs no CORS handling.

The shape worth reading:

```
frontend/src/
├── agui/                     the protocol client — no React, no DOM
│   ├── types.ts              the transcript and state types this app owns
│   ├── reduceEvent.ts        the AG-UI event stream folded into the view
│   ├── reduceEvent.test.ts   `npm test` (Node's built-in runner; no framework)
│   ├── sse.ts                POST + Server-Sent Events, buffered across partial reads
│   ├── storage.ts            what has to survive a reload, and why
│   ├── uuid.ts               run-scoped ids
│   └── useAgUiRun.ts         one conversation: envelope, view, persistence
├── components/
│   ├── Transcript.tsx        the message list: prose, reasoning and tool-call cards
│   ├── StatusStrip.tsx       what the agent is doing right now
│   ├── Composer.tsx          the input
│   └── Sidebar.tsx           the shared state, the Bearer token, threadId / runId
└── App.tsx                   the page header and the layout, and nothing else
```

The point of that split is that **the AG-UI event stream is the only source of truth for the UI**. One
pure function, `reduceEvent(view, event)`, folds the stream into everything on screen — transcript,
status, shared state — so each of its branches is one protocol event and nothing else. It imports
neither React nor the DOM, which is why it is unit-tested with no test framework at all.

The protocol event types come from `@ag-ui/core`, AG-UI's own TypeScript SDK, so the reducer's branches
and the outbound run envelope are both checked against the published wire format instead of a
hand-copied version of it that would drift. Every use of it is an `import type`, which makes it a
*devDependency* — nothing from it, nor its `zod` dependency, reaches the bundle. What the SDK
deliberately does not define is the shape of the shared state (`StateSchema` is `z.any()`, because that
shape is an agreement between one agent and one client), so `types.ts` declares this demo's own and
casts the incoming snapshot to it — an assertion, not a check, which is why every consumer reads it
defensively.

### If you are building a real frontend

This app is written to be *read* — it keeps the POST, the SSE parsing and the event fold in plain sight
because those mechanics are the point. For shipping a product, look at
[CopilotKit](https://docs.copilotkit.ai) instead: same people who authored the AG-UI protocol, and it
supplies the polished chat UI, generative UI and human-in-the-loop pieces this example deliberately does
not. Note that it expects a CopilotKit Runtime (a Node service) in front of the agent, so it is a
different architecture from this single-origin demo — worth knowing before you choose.

`OPENAI_API_KEY` must be set in the environment.

## What the surface looks like

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/agui/agents` | the names of the agents reachable over AG-UI |
| `POST` | `/agui/planner` | run a named agent |
| `POST` | `/agui` | run `agui.default_agent` |

A run is a `RunAgentInput` body in, and a stream of AG-UI events out: `RunStarted` first, then the
run's events, then exactly one of `RunFinished` or `RunError`. Which event types a given agent can
actually produce depends on its framework adapter — see the AG-UI page in the Agent Kernel docs for
the per-adapter matrix. A well-behaved client ignores event types it does not recognise, which is what
`reduceEvent.ts` does in its `default` branch.

The frontend renders four kinds of run event distinctly, because conflating them is what makes an
agent feel opaque:

| What | Events | Shown as |
|---|---|---|
| The answer | `TextMessageStart` / `Content` / `End` | prose, streamed in |
| The agent's reasoning | `ReasoningMessageStart` / `Content` / `End` | a separate dimmed "thinking" block, never mixed into the answer |
| A tool call | `ToolCallStart` / `Args` / `End` / `Result` | a card per call: name, the arguments as they stream in, then the result |
| What it is doing *now* | the run, step, message and tool-call boundaries | the status strip: Thinking, Calling `<tool>`, Replying, Idle |

That last row is what the protocol's boundary events are *for*. The status is read off the stream
rather than guessed from a timer, so it is accurate even when a step takes a long time.

Not every agent fills every row: an agent whose framework reports no reasoning simply never produces a
thinking block. The per-adapter matrix in the AG-UI docs page says which events each one can emit.

There is no `execution: mode: stream` in `config.yaml`, and that is deliberate: AG-UI delivers every
run as a stream by definition, so this surface does not consult the execution mode.

## Authorization

AG-UI has no open mode — `AGUIRequestHandler` refuses to construct without an `Authoriser` or an
`AuthValidator`, because its routes run agents on a caller's behalf. Agent Kernel does not
authenticate users itself: you supply an `Authoriser` subclass that validates the Bearer token
against your own provider and resolves the caller's `user_id`. Here `DemoAuthoriser` uses a static
token map (`demo-token` → `demo-user`), and the resolved user becomes the run's acting user.

## Client-supplied context

The browser attaches two things to every run, and neither reaches the prompt:

- `forwardedProps` — free-form passthrough (`page`, `locale` here)
- `context` — `{description, value}` pairs (the user's local time here)

Both land in the session's volatile cache, and the model has to *pull* them through the read-only
`get_forwarded_props()` and `get_agui_context()` tools, enabled by `agui.client_context`. That is
deliberate: flattening client text into the system prompt is what would turn a frontend into a prompt
injector. Ask the agent "what time is it for me?" to see it call one.

## Install and run

Install dependencies and build the frontend using:

    ./build.sh

The frontend build is skipped with a warning when `npm` is absent — the `/agui` routes and
`app_test.py` do not need it, and `GET /` then explains how to build it. To work on the frontend with
hot reload, run the Python app and Vite side by side; Vite proxies `/agui` through to :8000:

    python app.py
    cd frontend && npm run dev     # http://localhost:5173

Run the frontend's tests with:

    cd frontend && npm test        # needs Node 22.18+; Node strips the types, nothing compiles them
    cd frontend && npm run typecheck

`npm run build` runs the type check first, so `./build.sh` fails on a type error rather than shipping
one. There is no separate lint step: `make lint-examples-check` at the repo root covers Python only.

Install local dependencies in development mode using:

    ./build.sh local

**On a branch where the `agui` extra is not yet released, use `./build.sh local`.** The plain form
resolves `agentkernel` from PyPI, where the version matches but the `agui` extra does not exist yet —
and uv drops an unknown extra silently rather than failing, so the install appears to succeed and then
`AGUIRequestHandler` raises `ValueError: AG-UI support requires the 'ag-ui-protocol' package`.
`./build.sh local` resolves against `../../../ak-py/dist`, so run `ak-py/build.sh` first if that
directory is empty or stale.

**Start the app with `python app.py`, not `uv run app.py`, for the same reason.** `uv run` re-resolves
the environment before running, and on this branch that can replace the locally built `agentkernel`
with the published one — which has neither the `agui` module nor the extra. Activate the venv, or call
its interpreter directly:

    .venv/bin/python app.py

Run the app:

    python app.py

Then open <http://localhost:8000> and try:

- `add milk and bread to my tasks` — watch the panel fill in
- `mark milk done` — watch it update
- reload the page — the list and the transcript come back, and the agent still remembers the
  conversation, because the `threadId` is reused
- **New conversation** — a fresh `threadId`, so the agent's memory and the shared state both reset
- `what time is it for me?` — the agent reads the context the browser attached

## Talking to it without a browser

Discovery:

    curl http://localhost:8000/agui/agents -H "Authorization: Bearer demo-token"

A run:

    curl -N -X POST http://localhost:8000/agui \
      -H "Authorization: Bearer demo-token" \
      -H "Content-Type: application/json" \
      -d '{
            "threadId": "thread-1",
            "runId": "run-1",
            "state": {"tasks": []},
            "messages": [{"id": "m1", "role": "user", "content": "add milk to my tasks"}],
            "tools": [],
            "context": [],
            "forwardedProps": null
          }'

## Notes and limits

- `threadId` is Agent Kernel's `session_id`. Conversation history is rebuilt from the session store,
  so only the final `user` message in `messages` is read — there is no need to send the transcript.
- **The frontend keeps `threadId`, the state and the transcript in `sessionStorage`**, so a reload
  continues the same conversation rather than starting a new session. The state copy is not
  redundant: AG-UI has no "read the current state" request, and a `StateSnapshot` is only sent when
  the state *changes* during a run, so a reloaded page cannot ask the server what it holds. A client
  owning its copy and echoing it back as `state` is the protocol's model. Everything is scoped to the
  tab; **New conversation** clears it.
- Client-declared `tools` are ignored. Agent Kernel builds an agent's tool registry when the agent is
  constructed, so a tool named per-request has nothing to bind to.
- AG-UI state lives for the session's lifetime and is stored under a reserved session key. It is
  separate from any framework's own context.
- Audio and video content in a request body is rejected with a 400: Agent Kernel has no equivalent
  request type, and mapping it onto the generic file type produces misleading model output. Images
  and documents are accepted, from either an inline base64 `data` source or a `url` source.
