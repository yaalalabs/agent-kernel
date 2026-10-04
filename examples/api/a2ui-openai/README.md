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

```bash
export OPENAI_API_KEY=...
./build.sh
uv run app.py
```

Then:

```bash
curl -s localhost:8000/api/v1/chat \
  -H 'content-type: application/json' \
  -d '{"prompt": "I need to file an expense", "session_id": "s1", "agent": "expenses"}'
```

## Tests

```bash
uv run pytest
```

[`app_test.py`](app_test.py) asserts both halves: a UI turn arrives as an object with a label, and a
prose turn arrives as a plain string with none.
