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

**And the label survives being stored.** [`app.py`](app.py) mounts `AgentThreadRequestHandler`, so
every turn is recorded into a conversation thread. A recorded reply keeps its payload and its label,
which means reopening the conversation gives the frontend the same pair it got live:

```json
{"role": "assistant",
 "content": {"version": "v1.0", "createSurface": {"...": "..."}},
 "media_type": "application/a2ui+json"}
```

Without that, a form that rendered live would come back as a wall of JSON text — see
[Reload](#reload) below.

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
  -d '{"prompt": "I need to file an expense", "session_id": "s1", "user_id": "demo-user", "agent": "expenses"}'

# the same turn, read back out of thread history
curl -s localhost:8000/api/v1/threads/s1
```

`user_id` is **required** here and was not before: the thread handler owns these chat routes now,
and a thread belongs to someone. A real app resolves it from a token with an `Authoriser` rather
than trusting the body.

**Terminal 2 — the UI** (optional; the agent works without it):

```bash
cd frontend
npm install
npm run dev             # :5173, proxies /api through to :8000
```

`build.sh` does not build the frontend. The agent and `app_test.py` have no dependency on it, and
keeping them separate means a missing or broken npm never blocks the Python side.

## The frontend

~500 lines of React, counting the thread rail and the catalog:

```
frontend/src/
├── App.tsx              the chat box and the History rail; one branch on `media_type`
└── a2ui/
    ├── catalog.tsx      the nine components this client can draw
    ├── Surface.tsx      resolves ids and recurses — nothing else
    └── types.ts         the slice of A2UI this demo understands
```

**`catalog.tsx` is the whole point.** It is the same nine components listed in `app.py`'s prompt,
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
and the round trip still works, over the chat route that already exists. The agent answers that
submission with a summary surface rather than prose; [Reload](#reload) explains why that matters
more than it looks.

Two things make that round trip read correctly, and both are easy to miss:

- **The submitted form is disabled**, with a "Sent" note under it. Left live, it invites a second
  click that files the claim twice, and the transcript gives no sign the first one went anywhere.
- **The prompt tells the agent what a submission looks like** — a list of `field: value` pairs — and
  how to answer it: a summary card of read-only `Field`s when everything is there, prose naming the
  one missing field when it is not. What it must never do is render the editable form again, which
  looks exactly like the submission was lost.

The second is worth dwelling on. Nothing in Agent Kernel can fix it, because Agent Kernel never
looks inside the payload and has no idea a form was shown. Closing the loop is the application's
job, and it is mostly a prompting job.

## Reload

Turning on history is two things: the `thread` block in [`config.yaml`](config.yaml) picks the
store, and mounting `AgentThreadRequestHandler` is what actually enables recording. The handler
serves the same chat routes with recording wrapped around them, plus `GET /api/v1/threads` and
`GET /api/v1/threads/{session_id}` — the two routes the **History** rail in the UI reads.

To see the point: file an expense, then click the conversation again in **History**. The form comes
back as a form.

The interesting part is how little the frontend needed. `turnFor` in [`App.tsx`](frontend/src/App.tsx)
is the same function for both sources, because a live reply and a recorded message carry the same
pair:

| | payload | label |
|---|---|---|
| live reply | `result` | `media_type` |
| recorded message | `content` | `media_type` |

The names differ — one is a response, the other a stored message — but the shape does not, so there
is no second renderer and no "parse the string back into a document" step. Had the store kept the
payload as text, this example would need exactly that, and it would be the kind of code that works
until someone's reply contains a quote character.

### Why the confirmation is a surface

Submit the form and the agent answers with a **summary card** — a `Heading` and one read-only
`Field` per value — rather than a sentence. That is not decoration. `Field` carries its value
*inside the payload*, so the values are part of what gets labelled and stored, and they come back
on reload. Prose reads the same today and is just a sentence tomorrow.

It also shows what the filled form cannot do. After a live submit the form above still shows what
you typed, but only because those are uncontrolled inputs holding DOM state. Reload and it is empty
again — nothing recorded them. The values survive in exactly one place: the card the agent sent.

The submission itself is still an ordinary text message (`Cost centre: ENG-4, Amount: 250`), shown
as chips. `submittedFields` splits it **for display only**, and anything that does not split
cleanly falls back to the raw string — type a description with a comma in it and you will see that
happen. Nothing in the app reads the result. That is the line worth holding: a value the
application actually needs comes back inside a payload, never out of a string someone has to
re-split.

Two more details in the replay, both in `turnsFromThread`:

- **A recorded form is only disabled when something followed it.** A form left as the last message
  is still live, so a conversation you walked away from can be picked up; one that was answered
  cannot be answered twice.
- **Opening a thread sets the session id**, so the conversation genuinely resumes — the agent's own
  memory is keyed by the same id the thread is, not merely by what the transcript shows.

Both read routes are paginated — 50 threads, and 50 messages oldest-first — so `fetchAll` in
[`App.tsx`](frontend/src/App.tsx) follows `next_cursor` to the end before rendering anything. That
is not tidiness: the rule above only holds over a *complete* transcript, and a form that happened
to sit at message 50 would otherwise replay as live and be answerable a second time.

`thread.type: in_memory` keeps this to one command. History survives a reload of the page, which is
what is being demonstrated, but not a restart of `app.py`. Switch to `redis`, `valkey`, `dynamodb`,
`firestore` or `cosmosdb` for anything that has to outlive the process.

Thread names come from the first prompt, truncated. Add the `thread` extra
(`agentkernel[openai,api,thread]`) for an LLM-written title instead.

## Tests

```bash
uv run pytest
```

[`app_test.py`](app_test.py) asserts both halves twice over — live, and read back from thread
history. A UI turn arrives as an object with a label and is recorded as the same object with the
same label; a prose turn arrives as a plain string with no label and is recorded with no label at
all, not a null one. That last assertion is the one that pins what an application which never
turned A2UI on still reads back.
