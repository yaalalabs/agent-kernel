# #763: a labelled structured reply survives a thread reload — Implementation Spec

`ThreadMessage` gains the two fields a labelled payload needs — an object-capable `content` and a
`media_type` — and the one argument the queue path needs to hand its label over. Everything else
follows: the six store backends serialise the whole model and never read `content`, and the read
route dumps whatever the model holds. Requirements come from
[`design.md`](design.md); the decisions taken in review are its last section.

Code facts verified against `feature/706-a2ui-transport-agnostic` at `3ae17e25`. Paths are relative
to `ak-py/` unless stated otherwise.

---

## Design

### `ThreadMessage` (`src/agentkernel/integration/thread/model.py`)

Two field changes and one validator. The module gains
`from ...core.util.payload import JSONPayload` — `integration` importing `core` is the allowed
direction.

```python
class ThreadMessage(BaseModel):
    """A single message within a thread.

    ``content`` is text for every reply the agent did not label. When ``media_type`` is set it is
    the payload object instead — the same ``str | dict`` shape #706 gives ``result`` on the REST
    surface, so a client renders replayed history with the code it already renders a live reply
    with. The object branch is a ``JSONPayload``, so it runs the same normalisation
    ``AgentReplyAny.content`` runs and a value with no JSON form raises here rather than inside a
    store's ``model_dump_json``.

    The two fields move together, enforced rather than documented: a labelled message whose content
    is text, or an object with no label, would reach a client as a payload it cannot branch on.
    """

    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: Literal["user", "assistant"]
    content: Union[str, JSONPayload]
    media_type: Optional[str] = None
    timestamp: datetime.datetime = Field(default_factory=_utc_now)
    attachments: List[ThreadAttachment] = Field(default_factory=list)

    @field_validator("media_type", mode="before")
    @classmethod
    def _blank_label_is_no_label(cls, value: Any) -> Any:
        """Normalise a blank label to ``None`` before the pairing validator reads it.

        ``build_response`` and ``ThreadRecorder._as_thread_message`` both test the label for
        truthiness, so ``""`` already means unlabelled everywhere else; without this the wire form,
        which tests ``is None``, would be the one layer disagreeing. ``mode="before"`` means an
        object carrying a blank label raises the pairing validator's existing message.
        """
        if isinstance(value, str):
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def _label_and_payload_agree(self) -> "ThreadMessage":
        if self.media_type and isinstance(self.content, str):
            raise ValueError("media_type is set but content is text; a labelled message carries its payload as an object")
        if not self.media_type and not isinstance(self.content, str):
            raise ValueError("content is an object but media_type is unset; an unlabelled message carries text")
        return self

    def to_wire(self) -> dict:
        """The message as the thread read routes return it: ``media_type`` present only when set.

        Omitting an unset label rather than sending ``null`` matches the live reply, where
        ``ResponseBuilder.build_response`` adds the key only for a labelled payload
        (``core/chat_service.py:367-368``) — one branch in the client for both.

        The exclusion is named rather than ``exclude_none=True`` because ``exclude_none`` recurses:
        it would also drop an attachment's unset ``name`` and ``mime_type``, changing a shape no
        part of this work is about.
        """
        if self.media_type is None:
            return self.model_dump(mode="json", exclude={"media_type"})
        return self.model_dump(mode="json")
```

Rules this fixes in place:

1. **`media_type` is declared after `content` and before `timestamp`.** Field order is the key order
   in `model_dump_json()`, and both recording paths must produce the same bytes for the same reply
   (design.md, Requirements). One declaration site, so they do.
2. **`content`'s union is `str` first.** Under pydantic's smart union a `str` input matches the `str`
   member in strict mode and `PayloadCodec.normalise` never runs on it; a `dict` fails the `str`
   member and reaches `JSONPayload`. Even if the order were tried the other way, `normalise` raises
   `ValueError` for a non-dict/list (`core/util/payload.py`, `normalise`) and pydantic treats that as
   that member failing. Verified against the real models: `'hello'` and `'{"a": 1}'` both stay
   `str` (a JSON-*looking* string is never promoted to an object), a dict is normalised exactly as
   `AgentReplyAny.content` normalises it (`datetime` → ISO 8601, `Decimal` → `"250.00"`), and a
   scalar is rejected with a `ValidationError`. All four are pinned by tests rather than left to the
   union's internals.
3. **The wire form is the model's own method.** The read route must not assemble it, or the two read
   surfaces would be free to drift.
4. **`Union[str, JSONPayload]` rather than `str | JSONPayload`** — a style call, not a constraint.
   Both forms work (`str | JSONPayload` evaluates to the same `typing.Union`); the file already
   spells `Optional` and `List` the `typing` way, so `Union` is what the module reads like.

New imports in this module: `Any` and `Union` added to the `typing` import, `field_validator` and
`model_validator` to the `pydantic` import, and `from ...core.util.payload import JSONPayload`.

### `ThreadRecorder` (`src/agentkernel/integration/thread/recorder.py`)

`post_run` takes the label, and `_as_thread_content` is replaced by `_as_thread_message`, which
returns the pair instead of a string. The module gains `AgentReplyAny` to its existing
`from ...core.model import ...`.

```python
def post_run(self, req: BaseChatRequest, result: Any, media_type: Optional[str] = None) -> None:
    """Thread work done after a successful agent run: append the assistant message.

    ``media_type`` is how the queue runner hands over a label it holds *beside* the result rather
    than on it — ``ResponseBuilder`` put both in the response body and the runner has only that
    body. The direct handler holds the reply itself and passes nothing.

    :param req: The originating chat request
    :param result: The agent's reply, in whichever form the caller holds it
    :param media_type: The reply's label when the caller holds it separately from the result
    :return: None
    """
    content, label = self._as_thread_message(result, media_type)
    self._manager.append_message(req.session_id, "assistant", content, media_type=label)


@staticmethod
def _as_thread_message(result: Any, media_type: Optional[str] = None) -> tuple[Any, Optional[str]]:
    """Render a reply as the (content, media_type) pair the thread store holds.

    The callers pass three different things, which is what makes a single ``str()`` wrong. The
    direct handlers pass an ``AgentReply``; the streaming one passes the accumulated text; the queue
    runner passes the response body's ``result`` value, which for a labelled reply is a dict with
    its label in a sibling key. **A labelled reply is stored as the object** — that is the whole
    change — and everything else keeps the encoding it had, byte for byte.

    The ``default=str`` fallback on the unlabelled dict branch deliberately mirrors
    ``AgentReplyAny.__str__``'s own call rather than using ``PayloadCodec.encode``. For JSON-safe
    content the two agree; they part on a value that reached ``content`` through one of the
    documented bypasses, where ``default=str`` renders a datetime as the reply's ``__str__`` does
    and the codec renders it as ISO 8601. Matching the reply exactly is the point.

    :param result: An AgentReply, a plain string, or the response body's ``result`` value.
    :param media_type: The label when the caller holds it separately from the result.
    :return: The thread message content and its label, or the content and None.
    """
    if isinstance(result, AgentReplyAny) and result.media_type:
        return result.content, result.media_type
    if media_type and isinstance(result, (dict, list)):
        return result, media_type
    if isinstance(result, str):
        return result, None
    if isinstance(result, (dict, list)):
        return json.dumps(result, default=str), None
    return str(result), None
```

- An `AgentPausedReplyAny` never sets `media_type`, so it reaches the last branch and records
  exactly as today (`AgentReplyAny.__str__`).
- An unlabelled `AgentReplyAny` does the same. **The label is the switch**, as on every other
  surface.
- A dict with no label keeps `json.dumps(..., default=str)`. This path is reachable only from a
  caller passing a raw dict: `build_response` puts a *string* in `result` for an unlabelled reply.

### `ConversationThreadManager` (`src/agentkernel/integration/thread/manager.py`)

`append_message` gains the parameter **after** `attachments`, so `pre_run`'s existing call
(`recorder.py:57`, keyword `attachments=`) is untouched.

```python
def append_message(
    self,
    session_id: str,
    role: str,
    content: Union[str, dict, list],
    attachments: Optional[List[ThreadAttachment]] = None,
    media_type: Optional[str] = None,
) -> ThreadMessage:
    """...
    :param content: Message text, or the payload object when media_type is set.
    :param media_type: The payload's format when the reply carried one; None for text.
    """
    message = ThreadMessage(role=role, content=content, media_type=media_type, attachments=attachments or [])
    self._store.append_message(session_id, message)
    return message
```

No other method changes. The manager does not validate the pairing — `ThreadMessage` does, once.

### Consumer changes

**`src/agentkernel/pipeline/agent_runner.py`** — the one place the label is currently dropped.

- `process` (line 55) reads both keys off the response body instead of one. The single expression
  becomes two locals because the combined line exceeds the 150-character limit and reads worse:

  ```python
  body_is_dict = isinstance(agent_response, dict)
  result = agent_response.get("result") if body_is_dict else agent_response
  media_type = agent_response.get("media_type") if body_is_dict else None
  self._record_thread_reply(message, body, status_code, result, media_type)
  ```

- `_record_thread_reply` (line 117) gains `media_type: Optional[str] = None` as its last parameter
  and forwards it to `post_run`. Its docstring's `:param result:` line stops saying "recorded via
  ``str()``", which is no longer true for a labelled reply.
- **Verified unchanged**: the call stays *after* `_send_to_output`, the method still catches and logs
  every exception rather than re-running the agent, and the lazy import stays inside the method.
- `StreamAgentRunner` (line 242) passes no label and needs no edit: it records accumulated text, and
  structured output is non-streaming.

**`src/agentkernel/integration/thread/thread_chat.py`** — one expression.

- Line 380 becomes `body["messages"] = [message.to_wire() for message in page.messages]`.
- **Verified unchanged**: `list_threads` (lines 358-361) excludes messages entirely; the chat routes'
  `post_run` call (line 136) passes no label because the reply carries it; the ordering
  `post_run` → `build_response` (lines 136-137) is deliberate and stays.

**Verified unchanged, no edit:** all six `ThreadStore` backends. Each serialises the whole model and
parses it back the same way — `store/redis_like.py:124,152`, `store/dynamodb.py:155,203`,
`store/cosmosdb.py:145,177`, `store/firestore.py:126,152` — and `store/in_memory.py:63` appends the
model object itself. None reads `content`, and the ABC (`store/base.py:68`) takes the model.

### Config changes

**None.** Nothing here is selectable or deployment-dependent; the behaviour follows from a reply
already carrying a label. No new block, no `enabled` flag, no new `AKConfig` field, and no change to
`_ThreadStoreConfig`. Existing YAML and `AK_THREAD__*` env vars are unaffected.

### Behavioural changes

1. **A labelled reply's thread row holds the payload as an object and carries `media_type`.** The
   change the issue asks for.
2. **The queue path records the label.** `agent_runner.py:55` currently keeps `result` and discards
   the `media_type` sitting beside it in the same dict. Both paths now reach `ThreadMessage` with the
   same object and the same label, so the rows match structurally rather than by a shared encoder.
3. **`GET /api/v1/threads/{session_id}` returns `media_type` on labelled messages and omits the key
   on every other message.** Intentional: it matches `build_response`, which adds the key only for a
   labelled payload.
4. **A payload that bypassed `AgentReplyAny`'s validation now raises during recording rather than
   during response building** — `post_run` runs first (`thread_chat.py:136-137`). On the direct path
   the handler's own `except Exception` (`thread_chat.py:143-145`) turns it into the same 500 it
   returns today, and nothing is recorded, where today the malformed value is recorded as text and
   *then* the response fails. On the queue path nothing changes: `_record_thread_reply` already
   swallows and logs every recording failure (`agent_runner.py:156-157`) because the reply has
   already been delivered. Both paths still agree — neither records a row. Decided in review
   (design.md, Decisions).
5. **Every stored row written from now on carries a `media_type` key**, `null` for an unlabelled
   message, because the stores call `model_dump_json()` on the whole model. Stored bytes therefore
   differ from pre-change rows for every message, labelled or not. Unavoidable without special-casing
   serialisation in six backends, and invisible: `model_validate_json` reads old and new rows alike,
   and `to_wire` keeps the *read route's* output byte-identical for an unlabelled message.
6. **A bring-your-own `ThreadStore` that persists `message.content` into a typed text column now
   receives a dict for a labelled reply.** A documented breaking note, not a shim (design.md,
   Decisions).

**Non-changes** — verified, not assumed:

- The `ThreadStore` ABC signature and all six built-in backends.
- `Thread`, `ThreadPage`, `MessagePage`, `ThreadAttachment`; `ThreadMessage.message_id`, `role`,
  `timestamp`, `attachments`.
- `GET /api/v1/threads` (listings exclude messages).
- `ThreadRecorder.pre_run` and user messages: `req.prompt` is a `str`, so only assistant messages can
  ever carry either new form.
- `StreamAgentRunner`'s recording, and the streaming branch of `AgentThreadRequestHandler`
  (`thread_chat.py:178`).
- `_record_thread_reply`'s position after `_send_to_output` and its never-raising contract.
- Paused replies: `AgentPausedReplyAny` sets no `media_type`.
- Messaging integrations, which never record threads.
- Reading a thread written before this change: `media_type` defaults, `content` is a `str`, the
  validator's unlabelled branch passes.

### Per-operation cost

Recording a **labelled** reply runs `PayloadCodec.normalise` once more than before, inside
`ThreadMessage` construction, over a payload `AgentReplyAny` already normalised at construction and
`build_response` will normalise again. It is a `dump_json`/`loads` round trip over an A2UI surface
description — small, on a path that just finished an LLM call — and it is what makes the stored value
provably JSON-safe without the recorder reaching for the codec itself. Accepted. Nothing changes for
an unlabelled reply: the `str` union member runs no validator.

### Concurrency

Nothing new. `append_message` is unchanged in shape, the stores' atomic-append contract
(`store/base.py:70-72`) is untouched, and `ThreadMessage` is constructed per call with no shared
state.

## Error handling

| Failure | Where it surfaces |
|---|---|
| Labelled reply whose content bypassed validation (`model_copy` over `content`, in-place mutation) | `ThreadMessage` construction raises `ValueError`. Direct path: `thread_chat.py:143-145` → 500, nothing recorded. Queue path: `agent_runner.py:156-157` logs `"Failed to record the assistant message for session_id=..."`, reply already delivered. |
| A caller constructing a half state (object without a label, or a label with text) | The model validator raises `ValueError` naming which half is wrong. Reachable only from code calling the manager directly; `_as_thread_message` cannot produce one. |
| A blank or whitespace-only `media_type` | No error. `_blank_label_is_no_label` normalises it to `None` before the pairing validator runs, so text records as text and an object is refused as unlabelled. |
| Thread row written before this change | No error. `media_type` defaults to `None`, `content` validates as `str`. |
| A BYO `ThreadStore` that cannot hold an object | Its own exception, through the two routes above. Documented, not caught. |
| Missing `thread` config block, missing `user_id`, unavailable agent | Unchanged — all of it happens in `pre_run` or the handler, before any of this. |

## Testing

Run: `cd ak-py && uv run pytest tests/test_thread_integration.py tests/test_thread_pipeline_recording.py tests/test_cross_surface_parity.py tests/test_thread_router.py tests/test_thread_store.py tests/test_thread_manager.py`, then the full suite with `uv run pytest`.

### Changed — existing tests that assert today's behaviour

- **`tests/test_cross_surface_parity.py:139-147`**,
  `test_thread_history_records_the_same_bytes_from_either_path`. It calls
  `ThreadRecorder._as_thread_content` on both shapes and asserts the two JSON *strings* are equal.
  Rewritten against `_as_thread_message`: the direct call
  (`_as_thread_message(labelled_reply)`) and the queue call
  (`_as_thread_message(labelled_reply.content, MEDIA_TYPE)`) must both return
  `(EXPECTED_CONTENT, MEDIA_TYPE)`. Rename to `..._records_the_same_payload_from_either_path`.
- **`tests/test_cross_surface_parity.py:150-160`**, `test_every_surface_agrees_on_the_payload` — the
  file's reason for existing. Thread history joins the chain: the recorded content is asserted equal
  to `rest == async_body["result"] == stream[...] == agui.value == EXPECTED_CONTENT`. This is the
  assertion that would have caught the original divergence, so it is the one that must now cover the
  surface the issue is about.
- **`tests/test_thread_integration.py:288-337`**, `TestThreadContentEncoding` — its five methods call
  `_as_thread_content` and assert strings. They move to `_as_thread_message` and assert the pair,
  keeping every current expectation as the `None`-label case, plus a new labelled case per caller
  shape.
- **`tests/test_thread_integration.py:135`** —
  `manager.append_message.assert_called_once_with("s1", "assistant", "agent says hi")` gains
  `media_type=None`.
- **`tests/test_thread_pipeline_recording.py:274-287`**,
  `test_a_labelled_reply_is_recorded_as_json_not_a_python_repr` — its fake chat service returns
  `{"result": content}` with no label, so it is now testing the *unlabelled* dict branch. Keep it,
  renamed to say so, and add the labelled sibling below.

### New

- **`tests/test_thread_integration.py`**, on the model:
  - a `str` content stays a `str` and is not routed through `JSONPayload` (the smart-union
    assumption, pinned rather than trusted);
  - a dict content is normalised — a `datetime` and a `Decimal` in, their JSON forms out — matching
    what `AgentReplyAny.content` does with the same value;
  - the validator rejects an object with no label, and a label with text, each naming its half;
  - `model_validate_json` on a pre-change row (no `media_type` key) round-trips;
  - `to_wire()` omits `media_type` when unset, includes it when set, and **keeps an attachment's
    `name: null` / `mime_type: null`** — the regression guard for choosing a named exclusion over
    `exclude_none`.
- **`tests/test_thread_pipeline_recording.py`**, on the riskiest consumer (`AgentRunner.process`, the
  code that changes shape most): a chat service returning
  `{"result": content, "media_type": "application/a2ui+json", "session_id": "s1"}` produces a row
  whose `content` is the object and whose `media_type` is the label; and the stream runner still
  records text with no label.
- **`tests/test_thread_integration.py`**, end to end over `InMemoryThreadStore` and the real routes:
  a labelled reply recorded through `AgentThreadRequestHandler`, then read back from
  `GET /api/v1/threads/{session_id}`, arrives with `content` as an object and `media_type` set —
  and an unlabelled reply in the same thread arrives as a string with no `media_type` key.
- **`tests/test_thread_router.py`**: the read route's message shape for both message kinds, so the
  wire form is covered where the route is tested rather than only where the model is.

### Patch targets that move

`ThreadRecorder._as_thread_content` is referenced by name in `tests/test_cross_surface_parity.py` and
`tests/test_thread_integration.py`; both move to `_as_thread_message`. `manager.append_message`
`MagicMock` assertions (`tests/test_thread_integration.py:126,135`,
`tests/test_thread_pipeline_recording.py:309,324`) gain or tolerate the new keyword. No monkeypatched
module path changes.
