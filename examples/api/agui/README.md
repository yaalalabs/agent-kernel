# Agent Kernel over the AG-UI protocol

This package contains a demo of an Agent Kernel agent driven over [AG-UI](https://github.com/ag-ui-protocol/ag-ui),
an event-based protocol for talking to a user-facing frontend. The app mounts `AGUIRequestHandler`
(see `app.py`), which is what enables the AG-UI surface; the `agui` block in `config.yaml` only
parameterizes it.

The agent is an OpenAI Agents SDK agent that keeps a short task list in AG-UI's **shared state**. That
list is the point of the demo: the model amends it by calling `update_agui_state`, the server streams
the amended copy back as a `StateSnapshot`, the browser renders it in the right-hand panel, and the
browser echoes it on the next run. Neither side owns the list; both read and write it.

`frontend/` is a small **React + TypeScript** app (Vite). The usual way to run it is `npm run dev`
on :5173, which proxies `/agui` through to the Python app. `npm run build` is optional: it emits
`frontend/dist`, which `app.py` serves at `GET /` so the UI and the AG-UI routes share one origin.

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

**The demo agent fills three of the four rows out of the box.** Tool calls come from
`count_open_tasks` and from the shared-state tools, so a card appears whenever the agent reads or
writes the list. **Reasoning is opt-in**, because the model this example defaults to emits none and
running a reasoning model on every CI build would be slower and pricier for no gain:

    AK_DEMO_REASONING_MODEL=<a reasoning-capable model> python app.py

That switches the agent onto that model and asks for a reasoning *summary* — the summary is what the
adapter maps, so a reasoning model alone still renders nothing. With it set, ask for something worth
planning and the dimmed thinking block fills in above the answer, on its own message id.

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

## Attachments

The 📎 button attaches images and documents to a turn. `multimodal.enabled` is on in `config.yaml`, so
each one is described by a vision model and stored under the session before the agent runs — the agent
sees the description and an id, never the bytes. Ask a follow-up question the description cannot answer
and it calls the attachment-analysis tool with that id, which appears as a tool card like any other.

What the browser sends is AG-UI's typed content: `content` becomes a list of parts rather than a
string, an image going as an `image` part and anything else as a `document`, each with a `data` source
carrying bare base64.

```json
"content": [
  {"type": "text", "text": "what is this?"},
  {"type": "image", "source": {"type": "data", "value": "<base64>", "mimeType": "image/png"}}
]
```

Worth knowing:

- **Bare base64 is what the frontend sends**, and it is the form that works on every path. A `data:`
  URI and an `http(s)://` or `s3://` URL are also accepted, but a URL is passed through untouched —
  never described or stored — because the hook does not fetch it. See
  [Multimodal](../../../docs/docs/advanced/multimodal.md).
- **Audio and video are rejected with a 400.** Agent Kernel has no equivalent request type, and
  mapping them onto the generic file type produces misleading model output.
- **An attachment with no prompt is a valid turn**; the image is the content. A turn with neither is a
  400.
- The demo caps a file at 4MB. Base64 inflates a payload by about a third and it all travels inside one
  JSON body, so the cap fails loudly rather than letting the browser hang on a video.

### Testing it in the browser

Any screenshot or PDF you have to hand will do — the point is to watch two different paths.

1. **The description path.** Attach an image with 📎, send `what is in this image?`, and watch the
   answer arrive with **no tool card**. The attachment was described *before* the agent ran, so the
   description was already in its prompt and it had nothing to look up.
2. **The analysis path.** Now ask for something the description cannot contain — `read me the exact
   numbers in it`, or `quote the third line` — and a tool card appears for the attachment-analysis
   tool, with the attachment id in its arguments and the analysis as its result. That is the agent
   deciding the summary was not enough.
3. **Memory across turns.** Ask about the same image on a later turn *without* re-attaching it. Two
   separate things make that work: the description was appended to the earlier turn's prompt, so it is
   in the conversation history the session replays; and the bytes are still in the attachment store
   under this session, so the analysis tool can be called again on the same id.
4. **Reload the tab.** Your turns come back with `📎 <filename>` on them — the filenames are part of
   the transcript the frontend keeps in `sessionStorage`. That is the *tab's* memory, not the server's;
   a new tab starts a new `threadId` and therefore a new conversation.

Two things worth trying because they should *not* work:

- Attach an `.mp3` or `.mov`. The run is refused with a 400 naming the type before the stream opens —
  not a silent drop, which would read as the agent ignoring you.
- Attach something over 4MB. It is refused at the moment you pick it, before you have typed anything,
  and the reason appears in the transcript — the run is never attempted, so no prompt is swallowed.

Two things that look like bugs but are not. `storage_type` defaults to `in_memory`, so restarting
`app.py` drops the stored bytes: a follow-up question about an image attached before the restart can
still be answered from the description in the history, but the analysis tool will not find the id. And
if the 📎 button does nothing at all, the frontend was not rebuilt — run `./build.sh` (or
`cd frontend && npm run build`).

## Install and run

Install Python dependencies:

    ./build.sh

Then run the Python app and the Vite frontend side by side. Vite proxies `/agui` through to :8000:

    python app.py
    cd frontend && npm install && npm run dev     # http://localhost:5173

`./build.sh` does not build the frontend — the `/agui` routes and `app_test.py` do not need it, and
no CI job installs Node for this example. `GET /` on :8000 explains how to start the UI if
`frontend/dist` is missing.

Run the frontend's tests with:

    cd frontend && npm test        # needs Node 22.18+; Node strips the types, nothing compiles them
    cd frontend && npm run typecheck

`npm run build` type-checks and then emits `frontend/dist`, which `app.py` serves at `GET /` if you
want the UI on the same origin as the routes. There is no separate lint step:
`make lint-examples-check` at the repo root covers Python only.

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

Open <http://localhost:5173> and try:

- `add milk and bread to my tasks` — watch the panel fill in
- `mark milk done` — watch it update
- reload the page — the list and the transcript come back, and the agent still remembers the
  conversation, because the `threadId` is reused
- **New conversation** — a fresh `threadId`, so the agent's memory and the shared state both reset
- `what time is it for me?` — the agent reads the context the browser attached
- `how many tasks are left?` — a tool card appears for `count_open_tasks`, arguments and result
  included, and the status strip reads `Calling count_open_tasks` while it runs
- attach a screenshot with 📎 and ask `what is in this image?` — it is described before the agent runs,
  so the answer comes from the description; ask for a detail the description misses and the agent
  analyses the attachment itself, which shows up as another tool card
- with `AK_DEMO_REASONING_MODEL` set, `which of my tasks should I do first?` — the thinking block
  fills in first, then the answer, on two different message ids

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

A run with an attachment — `content` becomes a list of parts instead of a string:

    IMG=$(base64 -i screenshot.png | tr -d '\n')     # Linux: base64 -w0 screenshot.png

    curl -N -X POST http://localhost:8000/agui \
      -H "Authorization: Bearer demo-token" \
      -H "Content-Type: application/json" \
      -d '{
            "threadId": "thread-2",
            "runId": "run-1",
            "state": null,
            "messages": [{"id": "m1", "role": "user", "content": [
              {"type": "text", "text": "what is in this image?"},
              {"type": "image", "source": {"type": "data", "value": "'"$IMG"'", "mimeType": "image/png"}}
            ]}],
            "tools": [],
            "context": [],
            "forwardedProps": null
          }'

Swap `"type": "image"` for `"type": "document"` for a PDF or text file, and set `mimeType` to match.
A `url` source works too — `{"type": "url", "value": "https://..."}` — but a URL is passed through
untouched rather than described or stored, so the agent only sees the link.

## Tests

    .venv/bin/pytest -s

`.venv/bin/pytest` rather than `uv run pytest`, for the reason given above — the suite starts `app.py`,
so a re-resolve would test the published `agentkernel` instead of the one you built.

Requires `OPENAI_API_KEY`. The suite speaks AG-UI to the app over real HTTP, so it covers the whole
outbound chain: a real adapter, the AG-UI mapping, the SDK encoder and a live model. The two multimodal
cases assert structurally — the image part is accepted, the run brackets and finishes — rather than on
what a vision model says about a given picture, so they check the wiring without flaking on wording.

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
