# #607: Human-in-the-loop in conversation thread history — Implementation Spec

A paused run and the human's decision become structured thread messages instead of an empty bubble
and a JSON string. `ThreadMessage` gains a payload-or-text `content` with a `media_type` label;
`ThreadRecorder` learns two new shapes; and all four recording sites funnel a pause through the same
`AgentPausedReplyAny`, so the stored bytes are identical whichever surface ran the turn.
[`design.md`](design.md) is the requirements source; every requirement there is traced to a section
here.

## Design

### `integration/thread/model.py` — the message model

`ThreadMessage` carries either text or a payload object, and the label says which.

```python
class ThreadMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: Literal["user", "assistant"]
    content: str | JSONPayload          # was: str
    media_type: Optional[str] = None    # new, declared between content and timestamp
    timestamp: datetime.datetime = Field(default_factory=_utc_now)
    attachments: List[ThreadAttachment] = Field(default_factory=list)

    @model_validator(mode="after")
    def _label_and_payload_agree(self) -> "ThreadMessage": ...

    def to_wire(self) -> dict:
        """The message as the read routes return it; media_type omitted when unset."""
```

Rules this model is written to:

1. **`JSONPayload`, not `dict | list`.** `JSONPayload` (`core/util/payload.py:120`) runs
   `PayloadCodec.normalise` as a `BeforeValidator`, so a payload is coerced to plain JSON types at
   construction and a value with no JSON form raises here — naming the key path — rather than inside
   a store's `model_dump_json()`, where the failure would surface as a store error on a message that
   had already been accepted. It is the same annotation `AgentReplyAny.content` uses, so a reply's
   content and its thread copy are normalised by one implementation.
2. **Field order is wire order.** `media_type` is declared between `content` and `timestamp` because
   pydantic emits fields in declaration order, and all four recording sites must produce
   byte-identical `model_dump_json()` output for the same message (design.md, *Surface parity*).
3. **The two fields are one decision, enforced.** `_label_and_payload_agree` raises on a label over
   text and on an object with no label. Documented-but-unenforced would let a surface store an
   object a client cannot branch on.
4. **`to_wire()` excludes by name, not `exclude_none`.** `exclude_none` recurses, so it would also
   drop a `ThreadAttachment`'s unset `name` and `mime_type` and change a shape this work owes
   nothing to.

`media_type` is `"application/json"` for both HITL message kinds, exported as one module constant so
the three writers cannot drift:

```python
HITL_MEDIA_TYPE = "application/json"
"""The label on a pause or decision message: an object, not text. Deliberately not a vendor type —
`application/a2ui+json` names an external standard; Agent Kernel owns none for pause/resume."""
```

### `integration/thread/manager.py` — `append_message`

`content` widens to `Union[str, dict, list]` and `media_type: Optional[str] = None` is added after
`attachments`, forwarded to the `ThreadMessage` constructor. The parameter order of the existing
positional arguments (`session_id`, `role`, `content`) is unchanged, so every existing call site is
untouched.

### `integration/thread/recorder.py` — what is recorded

Two changes: the user side learns the decision shape, and the reply side returns a `(content, label)`
pair instead of a string.

```python
def pre_run(self, req, requests) -> tuple[List[AgentRequest], List[ThreadAttachment]]:
    ...
    content, media_type = self._as_user_message(req)
    self._manager.append_message(req.session_id, "user", content, attachments=attachments, media_type=media_type)

@staticmethod
def _as_user_message(req: BaseChatRequest) -> tuple[Any, Optional[str]]:
    """The turn as the request carried it: text, or the decision payload."""
    if req.resume is None:
        return req.prompt, None
    resume = {"resume": req.resume.model_dump(mode="json")}
    return ({"prompt": req.prompt, **resume} if req.prompt else resume), HITL_MEDIA_TYPE

def post_run(self, req, result: Any) -> None:
    content, label = self._as_thread_message(result)
    self._manager.append_message(req.session_id, "assistant", content, media_type=label)

@staticmethod
def _as_thread_message(result: Any) -> tuple[Any, Optional[str]]:
    if isinstance(result, AgentPausedReplyAny):
        return result.content, HITL_MEDIA_TYPE
    if isinstance(result, str):
        return result, None
    if isinstance(result, (dict, list)):
        return json.dumps(result, default=str), None
    return str(result), None
```

- **The decision dict is built as one literal, with `prompt` first.** Key insertion order is key
  order in `model_dump_json()`, so `{"prompt": ..., **resume}` is what pins the bytes; assigning
  `content["prompt"]` afterwards would emit the keys in the other order on the path that happens to
  take that branch.
- **`prompt` is included only when non-empty.** `BaseChatRequest.prompt` is `str = ""`
  (`core/model.py:53`), so a decision-only turn would otherwise carry a `"prompt": ""` key that
  means nothing.
- **The `AgentPausedReplyAny` branch is first**, before the `str`/`dict` branches, for the same
  reason #606 put pause detection before reply mapping in every adapter: the subclass would
  otherwise fall through to `str(result)` and be stored as text.
- **Every other branch is unchanged**, byte for byte — including the `default=str` fallback that
  matches `AgentReplyAny.__str__` rather than `PayloadCodec.encode`. The `(content, media_type)`
  pair and the `_as_thread_content` → `_as_thread_message` rename arrived with #763; this change
  adds one branch in front of them.
- **Neither method reads `ResumeDecision.status`.** `approved`, `denied` and `cancelled` reach the
  store inside the payload and nowhere else, so what is stored never depends on what a decision
  meant; rendering "nobody decided" is the client's job.
- **`post_run`'s `media_type` parameter is #763's, and no caller in this change passes it.** All
  four recording sites hand over an `AgentPausedReplyAny`, whose label comes from the branch above;
  the parameter carries a label the *queue* holds beside a labelled A2UI reply. Written originally
  as a seam for #817 and dropped again while it had no reader, it came back with that PR's merge,
  which is where its reader is.
- `media_type` is **not** read from `AgentPausedReplyAny.media_type`: that field is unset on a paused
  reply (only a post-hook sets one) and setting it would change the REST `202` body — see
  *Behavioural changes*, non-change 2.

### The four recording sites — one object, four sources

A pause is recorded by handing `post_run` an `AgentPausedReplyAny`. Three of the four sites do not
hold one, so they reconstruct it from what they do hold. The content is then derived in exactly one
place — the model's own `_derive_content` validator (`core/model.py:297-311`) — which is what makes
byte-identical storage structural rather than a convention four call sites must remember.

| Site | File:line | Holds | Becomes |
|---|---|---|---|
| Direct REST | `thread_chat.py:136` | the `AgentReply` | passed through unchanged |
| Direct SSE | `thread_chat.py:177` | a `RunPaused` event + `req.session_id` | `AgentPausedReplyAny(**event fields, session_id=req.session_id)` |
| Queue | `agent_runner.py:55` | the response body dict | built from its `run_id`/`agent`/`interruptions`/`session_id` keys |
| Queue streaming | `agent_runner.py:241` | the serialised chunk dict | built from `chunk["event"]` plus `chunk["session_id"]` |

#### Direct REST (`AgentThreadRequestHandler._run_with_recording`)

No change. `post_run` is already called unconditionally after `execute` (`thread_chat.py:136`), and
the reply it receives is the `AgentPausedReplyAny`; the new branch in `_as_thread_message` does the
rest.

#### Direct SSE (`AgentThreadRequestHandler._stream_with_recording`)

The `_stream()` generator gains a `paused` local alongside `deltas` and `error_seen`:

```python
if isinstance(chunk.event, RunPaused):
    paused = AgentPausedReplyAny(
        run_id=chunk.event.run_id, session_id=session_id,
        agent=chunk.event.agent, interruptions=chunk.event.interruptions,
    )
...
if paused is not None:
    recorder.post_run(req, paused)
elif not error_seen and deltas:
    recorder.post_run(req, "".join(deltas))
```

- **A paused run records the pause and nothing else**, even when text streamed before it. The
  non-streaming surfaces never had that text — `execute` returns the paused reply, not the partial
  message — so recording it here would make the same agent produce different history on two
  surfaces, which *Surface parity* forbids. The text is not lost to the user; it was streamed.
- The existing `deltas`-only guard is kept for the ordinary path, unchanged: it is what stops a
  halted or empty stream writing a blank assistant message.
- A pause is not an error, so `error_seen` is not set by it (`Runtime.stream` emits `RunPaused` as an
  ordinary chunk and ends with `done=True`, never through `StreamChunk.error`).

#### Queue (`AgentRunner.process`)

`process` decides what `result` means before handing it over; `_record_thread_reply`'s signature is
unchanged:

```python
result = agent_response.get("result") if body_is_dict else agent_response
if body_is_dict and agent_response.get("status") == "PAUSED":
    result = AgentPausedReplyAny(
        run_id=agent_response["run_id"], session_id=agent_response.get("session_id") or body.session_id,
        agent=agent_response["agent"],
        interruptions=[PausedInterruption(**i) for i in agent_response["interruptions"]],
    )
self._record_thread_reply(message, body, status_code, result)
```

- `status: "PAUSED"` is the discriminator the body already carries
  (`chat_service.py:374-380`), alongside `run_id`, `agent` and `interruptions` — the keys
  `build_response` promotes to the top level precisely so a client branches without parsing
  `result`. The runner is such a client.
- The existing guard `result in (None, "")` (`agent_runner.py:141`) is safe for a model instance:
  both comparisons are `==` against a `BaseModel`, which returns `False`.
- `status_code` for a pause is `202`, so the `>= 400` guard passes it through unchanged.

#### Queue streaming (`StreamAgentRunner.process`)

The chunk loop gains the same `paused` local, read off the serialised event rather than an object,
since this runner iterates JSON text (`agent_runner.py:230-238`):

```python
event = chunk.get("event") or {}
if event.get("type") == "run_paused":
    paused = AgentPausedReplyAny(
        run_id=event["run_id"], session_id=chunk.get("session_id") or body.session_id,
        agent=event["agent"],
        interruptions=[PausedInterruption(**i) for i in event["interruptions"]],
    )
...
if paused is not None:
    self._record_thread_reply(message, body, 202, paused)
elif not error_seen and deltas:
    self._record_thread_reply(message, body, 200, "".join(deltas))
```

- `"run_paused"` is `RunPaused.type`'s literal (`core/event.py:209`). The chunk's shape is
  `StreamChunk.model_dump(mode="json", exclude_none=True)` plus `session_id`
  (`chat_service.py:413-414`), so the event's fields arrive as plain JSON and
  `PausedInterruption(**i)` reconstructs each one.
- The hardcoded `200` is replaced by `202` on the paused branch. It feeds only the `>= 400` guard,
  but a paused run recorded as `200` would be the one place in the codebase where a pause claims to
  have completed.

### `integration/thread/thread_chat.py` — the read route

`get_thread` renders through the new method:

```python
body["messages"] = [message.to_wire() for message in page.messages]   # was: message.model_dump(mode="json")
```

Without it, `model_dump(mode="json")` would emit `"media_type": null` on every message ever written,
changing the read-route response for threads that have nothing to do with this feature.
`list_threads` dumps `Thread` with `exclude={"messages"}` and needs no change.

### Consumer changes

| Consumer | Change |
|---|---|
| `integration/thread/model.py` | `ThreadMessage.content` widened, `media_type` added, validator and `to_wire()` added, `HITL_MEDIA_TYPE` exported |
| `integration/thread/manager.py` | `append_message` takes `media_type` and a widened `content` |
| `integration/thread/recorder.py` | `_as_user_message` added; `_as_thread_content` → `_as_thread_message` returning a pair; `pre_run`/`post_run` updated |
| `integration/thread/thread_chat.py` | one line in `get_thread`; `_stream_with_recording` records a pause |
| `pipeline/agent_runner.py` | `AgentRunner.process` and `StreamAgentRunner.process` build the paused reply; `_record_thread_reply` unchanged |
| `integration/thread/store/*` | **Unchanged** — verified: all six persist the whole model (`redis_like.py:124,152`, `dynamodb.py:155,203`, `firestore.py:126`, `cosmosdb.py:145`) or hold the objects (`in_memory.py:22`) |
| `core/model.py`, `core/event.py`, `core/runtime.py`, `core/paused_run.py` | **Unchanged** — #607 reads the #606 vocabulary and adds nothing to it |
| `core/chat_service.py` | **Unchanged** — the `202` body already carries every key the queue path needs |
| `integration/agui/` | **Unchanged** — AG-UI records no threads (design.md, Non-goals) |

### Config changes

**None.** No new block, no new field, no `enabled` flag, no new extra. Verified against
`grep "class _" core/config.py`: the feature selects no backend and describes no connection.
Human-in-the-loop is active whenever a framework pauses (#606), threads are enabled by the `thread`
block plus a mounted thread handler, and both holding together *is* this feature's enablement.
`JSONPayload` lives in `core/util/payload.py`, so no optional dependency is involved. Existing YAML
and `AK_*` env vars are unaffected.

### Behavioural changes

1. **A decision is recorded as its payload instead of an empty message.** Intentional, and the
   defect the issue names: `pre_run` wrote `req.prompt`, which is `""` on a resume-only request.
2. **A paused reply is recorded as an object with a label instead of a JSON string.** Intentional.
   A client that read `content` as text for a paused turn now receives an object; this is the point
   of the change, and no client can have depended on it since the string was undocumented.
3. **The direct SSE path records a pause where it previously recorded nothing.** Intentional —
   the `deltas`-only guard silently dropped every paused streamed run.
4. **The queue streaming path records a pause where it previously recorded nothing**, and under
   `202` rather than `200`. Intentional, same gap.
5. **A streamed run that emits text and then pauses records only the pause.** Intentional, forced by
   *Surface parity*: the non-streaming path never had that text.
6. **The thread read route returns `content` as an object with a sibling `media_type` for the two new
   message kinds.** Intentional. For every other message the response is byte-identical, because
   `to_wire()` omits an unset `media_type`.
7. **`ThreadRecorder._as_thread_message` gains a branch, ahead of its existing ones.** Intentional;
   it is a private static method, and the ordering is what keeps a paused reply — an `AgentReplyAny`
   subclass carrying no label of its own — from falling through to `str(result)`.

**Non-changes**, stated so a reviewer can confirm them:

1. `ThreadMessage.role` stays `Literal["user", "assistant"]`; `Thread`, `ThreadAttachment`,
   `MessagePage` and `ThreadPage` are untouched.
2. `AgentPausedReplyAny.media_type` stays unset, so `build_response` keeps taking the `str(result)`
   branch (`chat_service.py:369-372`) and the REST `202` body is unchanged.
3. The `202` + `status: "PAUSED"` body, the AG-UI interrupt outcome, `RunPaused`, `QueueMessage`
   attributes and `ATTR_THREAD`'s meaning are all unchanged.
4. `_record_thread_reply`'s signature, its three guards and its after-`_send_to_output` ordering are
   unchanged.
5. The six thread store backends and the stored JSON of every pre-change message.
6. `ThreadRecorder.pre_run`'s ordering — `store_attachments` before `get_or_create_thread` before
   `append_message` — and its `user_id` enforcement.

**Data compatibility.** A message written before this change reads back identically: `content` is a
`str`, `media_type` is absent and defaults to `None`, and the validator's second branch accepts text
without a label. A message written after this change and read by an older Agent Kernel fails
validation on the unknown `media_type` key only if that version forbids extra keys — pydantic's
default is to ignore them, and `ThreadMessage` sets no `model_config`, so it is ignored.

## Error handling

| Failure | Surfaces as |
|---|---|
| A decision payload with no JSON form (`NaN`, an unserialisable object) | `ValueError` from `PayloadCodec.normalise` naming the key path, raised while constructing the `ThreadMessage` inside `pre_run` → the handler's existing `ValueError` → `400` branch (`thread_chat.py:138`), before the run. The queue handler maps it the same way (`thread_chat.py:304-306`). In practice unreachable from a REST body, whose payload already survived pydantic's JSON parsing. |
| A label without an object, or an object without a label | `ValueError` from `_label_and_payload_agree`. A programming error in a writer, not a user input; it fails loudly at construction rather than storing an unbranchable message. |
| A pause reconstructed from a malformed queue body or chunk | `KeyError`/`ValidationError` inside `AgentRunner.process`. For the non-stream runner this is before `_record_thread_reply`'s own `try`, so it fails the message and the input is retried — correct, because the reply has *already* been sent to the output queue and the caller is not waiting. For the stream runner the same applies after the chunks have been sent. Both bodies are built by `build_response`/`stream_chunk` in the same process family, so a malformed one is a bug, not an input. |
| A thread store failure while appending a pause | Unchanged: `_record_thread_reply`'s blanket `except Exception` logs and returns (`agent_runner.py:156-157`), and the direct handler's `post_run` failure becomes its `500` branch. |
| A runner with no `thread` block | Unchanged: the existing warning naming the missing configuration (`agent_runner.py:150-154`). |

## Testing

Run with `cd ak-py && uv run pytest`.

### Changed tests

| File | What changes |
|---|---|
| `tests/test_thread_integration.py` (`TestThreadContentEncoding`) | **Unchanged by this spec.** #763 rewrote these cases around the `(content, label)` pair and they cover the labelled-reply branches; this change adds its own cases beside them rather than touching them. |
| `tests/test_cross_surface_parity.py` | Gains the four-site pause parity case; #763's labelled-reply case is untouched. |
| `tests/test_thread_integration.py:97-138` (`TestThreadRecorder`) | Two `append_message.assert_called_once_with(...)` calls gain `media_type=None`. The recorded message is unchanged; the recorder now passes the argument explicitly. |
| `tests/test_thread_integration.py:417+` (`TestThreadPauseAndResume`) | Extended rather than changed — the two existing cases (the `202`, the promptless resume) keep passing. |

### New tests

In `tests/test_thread_integration.py`, extending `TestThreadPauseAndResume`:

- A decision-only request records one user message whose `content` is `{"resume": {...}}` and whose
  `media_type` is `application/json` — and **not** an empty string.
- A decision sent with a prompt records **one** message carrying both keys, `prompt` first.
- The three `ResumeDecision` statuses produce structurally identical messages.
- A paused reply records an assistant message whose `content` equals the reply's `content` and whose
  label is set.
- A decision rejected by `Runtime` leaves its user message and no assistant message (drive
  `_run_with_recording` with a `FakeChatService` raising `ValueError`, assert the `400` and the
  store's contents).
- `to_wire()` omits `media_type` for a text message and includes it for a payload one.
- The validator raises on both halves of the invalid pair.
- A pre-change message (`ThreadMessage(role="user", content="hi")`) still constructs and round-trips
  through `model_dump_json()`/`model_validate_json()`.

In `tests/test_thread_integration.py`, for the SSE path: a stream whose chunks end in a `RunPaused`
event records the pause; one that streams text *then* pauses records only the pause; an ordinary
stream still records the accumulated text.

In `tests/test_thread_pipeline_recording.py`, beside the existing reply-recording cases
(`:266-340`) and the `TestStreamRunnerRecording` cases (`:343-375`): a `PAUSED` response body records the pause message; a
streamed run ending in a `run_paused` chunk records it; both assert the stored message equals the
one the direct handler produces for the same reply.

In `tests/test_cross_surface_parity.py`: one paused reply recorded through the direct handler and
through both queue runners produces identical stored bytes — the parity this spec's single-object
design exists to guarantee.

`tests/test_thread_router.py` gains one case: a thread holding a pause and a decision reads back
through `GET /api/v1/threads/{session_id}` with objects in `content` and the label beside them.

### Documentation

| File | Change |
|---|---|
| `docs/docs/advanced/threads.md` | the two new message kinds, the `content`/`media_type` pair, and the worked example from `design.md` |
| `docs/docs/advanced/human-in-the-loop.md` | one section: what a pause looks like in thread history, pointing at the threads page |
| `docs/docs/api/rest-api.md` | the thread read route returning an object `content` with a sibling `media_type`, and that the key is absent for a text message |
| `examples/api/thread-openai/README.md` | the gated tool, the pause/resume exchange, and the stored shape |

### Example

`examples/api/thread-openai/` gains a gated tool:

- `app.py` binds one function with `OpenAIToolBuilder.bind([...], needs_approval=True)` and attaches
  it to `assistant_agent` — the only change to the agent.
- `app_test.py` gains the DoD's happy path: ask → `202` with `status: "PAUSED"` → resume with a
  decision → the thread read route shows the question, the decision and the answer in order → one
  follow-up ordinary turn in the same thread still works.
- `README.md` documents the stored shape with the worked example from `design.md`.
- No `config.yaml` change: `thread.type: in_memory` already enables recording, and HITL needs no
  configuration.
