# A2UI over REST

An agent that answers with a user interface when one helps, and with prose the rest of the time.

## What this shows

`a2ui.enabled` in [`config.yaml`](config.yaml) is the whole integration. With it on, a reply from a
named agent that parses as JSON is labelled `application/a2ui+json`, and the REST response carries
the payload as an object:

```json
{
  "result": {"version": "v1.0", "createSurface": {"surfaceId": "expense_form", "components": [...]}},
  "media_type": "application/a2ui+json",
  "session_id": "..."
}
```

A prose turn is unaffected — `result` is the string it has always been, with no `media_type` at all:

```json
{"result": "Hi — what would you like to claim for?", "session_id": "..."}
```

That is the contract: **the label is the switch.** Without one, every surface behaves exactly as it
did before this feature existed.

## What Agent Kernel does not do

**It ships no catalog.** The component list in [`app.py`](app.py) is this application's, because a
catalog has to match the components a given frontend can actually draw. One listing components your
client cannot render is worse than no catalog at all — the model emits them confidently and nothing
appears.

It also does not parse, validate, or interpret the payload. A reply that parses is labelled and
forwarded; whether it is *good* A2UI is the renderer's judgement, at the one place that knows which
components exist.

**There is no post-hook in this example.** Handling the reply is two config keys. If your format is
not A2UI, the extension point is still there: write a `PostHook` that sets `media_type` to whatever
you like, and every surface carries it the same way.

## Running it

Two terminals. The agent and the UI are separate processes, and the agent is useful on its own.

**Terminal 1 — the agent:**

```bash
export OPENAI_API_KEY=...
./build.sh local        # `local` installs agentkernel from ../../../ak-py/dist
uv run app.py           # :8000
```

```bash
curl -s localhost:8000/api/v1/chat \
  -H 'content-type: application/json' \
  -d '{"prompt": "I need to file an expense", "session_id": "s1", "agent": "expenses"}'
```

**Terminal 2 — the UI** (optional; the agent works without it):

```bash
cd frontend
npm install
npm run dev             # :5173, proxies /api through to :8000
```

`build.sh` does not build the frontend. The agent and `app_test.py` have no dependency on it, and
keeping them separate means a missing or broken npm never blocks the Python side.

## The frontend

~270 lines of React, and more than half of it is the catalog:

```
frontend/src/
├── App.tsx              the chat box; one branch on `media_type`
└── a2ui/
    ├── catalog.tsx      the eight components this client can draw
    ├── Surface.tsx      resolves ids and recurses — nothing else
    └── types.ts         the slice of A2UI this demo understands
```

**`catalog.tsx` is the whole point.** It is the same eight components listed in `app.py`'s prompt,
as React components — two copies of one list, on purpose. The agent is told what exists *there*; the
browser can draw what exists *here*. They have to agree.

Try breaking that agreement: add a component to the prompt in `app.py` and not to `catalog.tsx`. The
model will emit it confidently, and the renderer draws a dashed box reading
**⚠ Unknown component "…"**. That failure is why Agent Kernel ships no catalog — it cannot know what
your frontend implements, so any catalog it supplied would be wrong for somebody.

`Surface.tsx` is deliberately dumb: look up `root`, render it, recurse through `children` by id. No
validation, no data binding, no surface lifecycle. It does not judge whether the payload is *good*
A2UI either — Agent Kernel labelled it without looking inside, and the renderer is the first party
that knows which components exist.

Submitting a form sends the values back as an **ordinary next message** ("Cost centre: ENG-4, Amount:
250"). A2UI defines a callback path; this example does not use it, which is what render-only means —
and the round trip still works, over the chat route that already exists.

Two things make that round trip read correctly, and both are easy to miss:

- **The submitted form is disabled**, with a "Sent" note under it. Left live, it invites a second
  click that files the claim twice, and the transcript gives no sign the first one went anywhere.
- **The prompt tells the agent what a submission looks like** — a list of `field: value` pairs — and
  to answer it with prose: a confirmation naming the values, or a request for the one field that is
  missing. Without that the model reads the submission as a fresh request and renders the same form
  again, which looks exactly like the submission was lost.

The second is worth dwelling on. Nothing in Agent Kernel can fix it, because Agent Kernel never
looks inside the payload and has no idea a form was shown. Closing the loop is the application's
job, and it is mostly a prompting job.

## Tests

```bash
uv run pytest
```

[`app_test.py`](app_test.py) asserts both halves: a UI turn arrives as an object with a label, and a
prose turn arrives as a plain string with none.
