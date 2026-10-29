# #607: Human-in-the-loop in conversation thread history — Design Spec

A paused run and the human's decision are currently invisible or wrong in a thread: the decision
records as an empty message and the question records as a JSON string, when it records at all. This
change makes both of them first-class thread messages carrying their own structured payload, inside
the existing `user`/`assistant` role vocabulary, so a client replays a paused conversation with the
same branch it renders a live one with.

## Motivation

- **#606 deliberately left the thread integration untouched.** Its spec lists
  `integration/thread/recorder.py` as *Unchanged* and names the consequence: "a resume-only request
  records an empty user turn because `pre_run` writes `req.prompt`; a paused reply is appended like
  any assistant message" (`docs/specs/606-human-in-the-loop/spec.md:759`). `ThreadRecorder`,
  `ConversationThreadManager` and the thread models are listed again under **Non-changes**
  (`spec.md:816`). This change is that deferred work.
- **A decision records as an empty message.** `ThreadRecorder.pre_run` appends `req.prompt`
  (`recorder.py:57`), and `BaseChatRequest.prompt` is `str = ""` precisely so a resume can arrive
  without one (`core/model.py`, #606's one public-model change). `append_message` stores whatever it
  is given (`manager.py:140`) — there is no empty-content guard — so every approval writes a blank
  user bubble.
- **A pause records as a JSON string.** `post_run` renders the reply through `_as_thread_content`
  (since renamed `_as_thread_message` by #763)
  (`recorder.py:67,70`), whose final branch is `str(result)`. For an `AgentPausedReplyAny` that is
  `AgentReplyAny.__str__`'s JSON dump of the derived `content` — correct JSON, but typed as text, so
  a client must sniff a string to discover it is holding a pause.
- **The four recording sites disagree about the same exchange.**
  - Direct REST records the pause: `_run_with_recording` calls `post_run` unconditionally after
    `execute` (`thread_chat.py:136`), whatever `ChatService.success_status` then returns
    (`chat_service.py:636`, `202` for a paused reply).
  - Direct SSE records **nothing**: `_stream_with_recording` only records when text accumulated —
    `if not error_seen and deltas` (`thread_chat.py:177`) — and a run that pauses produces a
    `RunPaused` event with no `TextDelta`, so `deltas` is empty.
  - Queue mode records the string: `AgentRunner.process` forwards `agent_response.get("result")`
    (`pipeline/agent_runner.py:55`, `117`), which for a pause is that same JSON string.
  - Queue streaming records **nothing**, and would record it as `200`: `StreamAgentRunner` has the
    same deltas-only guard and passes a hardcoded status (`pipeline/agent_runner.py:241-242`).
- **The structure the queue path needs is already in the response body, just not forwarded.**
  `ResponseBuilder.build_response` promotes `status`, `run_id`, `agent` and `interruptions` to
  top-level keys for an `AgentPausedReplyAny` (`chat_service.py:374-380`). `AgentRunner.process`
  passes only `result` to the recorder, so those keys are dropped at the one boundary that needs
  them.
- **`ThreadMessage` can only hold text.** `content: str` (`integration/thread/model.py:33`), and the
  read route returns `message.model_dump(mode="json")` (`thread_chat.py:380`). There is no slot for
  a structured payload and no field a client can branch on.
- **The vocabulary to describe a pause already exists and is public.** `PausedInterruption`
  (`core/event.py:170`), `ResumeSpec` (`core/model.py:184`) and `ResumeDecision`
  (`core/model.py:143`) are the shapes the REST `202` body and the `resume` request block already
  carry. Nothing new has to be invented to describe a pause in history.

## Requirements

### Message model (`integration/thread/model.py`)

- `ThreadMessage.content` widens from `str` to `str | JSONPayload` — text, or a payload object.
  - `JSONPayload` (`core/util/payload.py:120`) is reused rather than a bare `dict`, so the payload
    runs the same normalisation `AgentReplyAny.content` runs and a value with no JSON form raises at
    construction rather than inside a store's `model_dump_json`.
- `ThreadMessage` gains `media_type: Optional[str] = None`.
  - Declared **between `content` and `timestamp`**: field order is key order in `model_dump_json`,
    and all three recording paths must produce identical bytes for the same message.
- The two fields are one decision, enforced by a model validator rather than documented: an object
  with no label, or a label over text, must raise.
- `media_type` for both HITL message kinds is **`application/json`**.
  - Deliberately not an invented vendor type. `application/a2ui+json` names a real external
    standard; Agent Kernel does not own one for pause/resume and will not mint one.
  - Consequence, accepted: the label says "object, not text" and does not discriminate. A client
    discriminates on `role` plus the payload's own top-level key — `interruptions` for a question,
    `decisions` for an answer — both of which are already public API.
- **No thread store changes.** All six backends persist the whole model rather than mapping fields:
  `redis`/`valkey` (`store/redis_like.py:124,152`), `dynamodb` (`store/dynamodb.py:155,203`),
  `firestore` (`store/firestore.py:126`) and `cosmosdb` (`store/cosmosdb.py:145`) round-trip through
  `ThreadMessage.model_dump_json()` / `model_validate_json()`, and `in_memory`
  (`store/in_memory.py:22`) holds the objects themselves. A widened field and a new optional one are
  carried by all of them unchanged.
- **No new classes.** This change adds behaviour to `ThreadMessage`, `ThreadRecorder`,
  `ConversationThreadManager` and the two queue runners; it introduces no component, and therefore
  no ABC, factory or contract suite.
- A rendering method on the model returns the message as the read routes send it, omitting
  `media_type` when unset.
  - Omitting rather than emitting `null` keeps the existing read-route response byte-identical for
    every message written before this change.
  - It must exclude that one field by name, not via `exclude_none`, which recurses and would also
    drop an attachment's unset `name`/`mime_type`.

### What is recorded (`integration/thread/recorder.py`)

**The governing rule: each side stores the Agent Kernel object that crossed its own boundary,
unmodified.** The recorder reshapes nothing, interprets nothing, and branches on no framework.

- A paused reply is recorded as `role: "assistant"`, `content` = the paused reply's own `content`
  (`run_id`, `session_id`, `agent`, `interruptions`), `media_type` = `application/json`.
- A decision is recorded as `role: "user"`, `content` = the request's own HITL-bearing fields, with
  the validated `ResumeSpec` nested whole under `resume`, `media_type` = `application/json`:
  - decision alone → `{"resume": {"run_id": …, "decisions": [...]}}`
  - decision with words → `{"prompt": "…", "resume": {…}}` — one message, because the words belong
    to the decision, and `prompt`/`resume` are siblings on `BaseChatRequest` already.
  - `ResumeSpec` is stored **nested rather than flattened** so the stored object remains exactly a
    `ResumeSpec` (`core/model.py:184`): flattening would put a thread-owned `prompt` key inside Agent
    Kernel's own namespace, where a later `ResumeSpec` field could collide with it and a reader
    could not tell the two apart.
  - `ResumeSpec` is surface-neutral — AG-UI supplies no `run_id` and REST does, but both arrive as
    the same validated model — so the stored message does not reveal which surface sent it.
  - `role: "user"` because a person sent it. The `Literal["user", "assistant"]` vocabulary
    (`model.py:32`) is **not** extended — a third role would be a stored-format change across all
    six thread backends and would break every client that exhaustively switches on `role`.
- Every decision is recorded identically, whatever it says. The recorder must not branch on
  `ResumeDecision.status` (`core/model.py:157`): `approved`, `denied` and `cancelled` are rendering
  concerns, and storing them differently would make history depend on what a decision *meant*.
- A decision the runtime later rejects is still recorded, for the same reason a prompt is: recording
  happens before the run on every surface, so the outcome is not knowable at write time.
  - Rejections raised *before* the runner — an unknown interruption id, an agent mismatch, a runner
    that cannot resume, or an adapter's own rejection (#606 places those above the adapter's `try`)
    — produce a `ValueError` → `400` and no agent turn at all, so no assistant message follows. The
    decision row is left orphaned, which is the same shape any failed turn already has today
    (`thread_chat.py:138`).
  - Failures raised *inside* the runner are unaffected: every adapter returns
    `AgentReplyText(user_facing_error_message(e))`, which is an ordinary reply and is recorded as
    one.
- `pre_run` must record this payload instead of `req.prompt` when the request carries a `resume`
  block, and must not write an empty-content message.
- Every reply that is not a paused reply keeps the exact encoding it has today, byte for byte. The
  label is the switch; nothing else about that method's existing branches changes.
- `post_run` must accept the pause's structure from a caller that holds it separately from `result`
  (the queue runner), since that caller has only the response body.

### Surface parity

- All four recording sites must store the same message for the same exchange:
  - **Direct REST** (`thread_chat.py:136`) — already calls `post_run` on a paused reply; only the
    rendering changes.
  - **Direct SSE** (`thread_chat.py:177`) — must record a pause. The `deltas`-only guard stays for
    ordinary runs (it is what keeps a halted or empty stream from writing a blank message), but a
    terminal `RunPaused` event must be recorded even though the run produced no text.
  - **Queue** (`pipeline/agent_runner.py:55`, `117`) — must receive the pause's structure. The pause
    keys `build_response` already puts on the body (`chat_service.py:374-380`) are forwarded to the
    recorder.
  - **Queue streaming** (`pipeline/agent_runner.py:241-242`) — same gap as direct SSE, plus a
    hardcoded `200` that a paused run must not be recorded under.
    - Specifically **not** by setting `media_type` on `AgentPausedReplyAny`: that would route the
      reply through `build_response`'s object branch (`chat_service.py:367`) and change the REST
      `202` body's `result` from a string to an object — a public change to the surface #606 just
      shipped, for a reason internal to the thread integration.
- A thread whose pause was recorded by one surface must be answerable and readable through any
  other; nothing in the message distinguishes which surface wrote it.

### Read surface

- `GET /api/v1/threads/{session_id}` returns the payload object as an object, with `media_type`
  beside it, so a client parses once.
- A message written before this change reads back identically: no `media_type` key, `content` still
  a string.

### Configuration

- **No configuration changes.** No new block, no new field, no `enabled` flag.
  - HITL is already always-on when a framework pauses (#606's Definition of Done), and thread
    support is already enabled by the presence of the `thread` block plus a mounted thread handler.
    Both conditions holding *is* the enablement for this feature; nothing is left to select.

### Documentation and example

- `docs/docs/advanced/threads.md` and `docs/docs/advanced/human-in-the-loop.md` both describe the
  stored shape, from their own side.
- `docs/docs/api/rest-api.md` documents the thread read route returning an object payload.
- `examples/api/thread-openai` gains the runnable path: one tool bound with `needs_approval=True`,
  so the example already under thread recording is the one that pauses.
  - Not `examples/api/hitl`, whose showcase surface is AG-UI — not a thread-recording surface, so
    the feature would not be visible in its console.
  - Its test is the DoD's happy path end to end: ask → pause → resume → a follow-up turn in the
    same thread, proving history stays coherent after a resume.

### Testing

- Pause and resume recorded correctly on each of the four recording sites (direct REST, direct SSE,
  queue, queue streaming), asserting the stored `content`, `media_type` and `role`.
- A full exchange — ask, pause, decide, answer — reads back from the thread store in order with the
  decision's payload intact.
- A decision sent with a prompt is stored as **one** message carrying both keys.
- The three decision statuses produce structurally identical messages.
- A decision rejected before the runner leaves its own message and no assistant message.
- Cross-surface parity: the same exchange recorded through the direct handler and through the queue
  produces identical stored bytes.
- A message written in the pre-change shape (`content` a string, no `media_type`) still loads.
- The validator rejects both halves of the invalid pair: a label over text, and an object with none.
- An ordinary (unpaused) run's stored message is unchanged, byte for byte.

## Non-goals

- **No new role.** `user`/`assistant` stays closed (see the requirement above for why).
- **No change to the pause/resume lifecycle.** `PausedRunState`, `Runtime`'s dispatch and
  validation, and every adapter's `resume`/`resume_stream` are untouched; this change records what
  already happens.
- **No change to the REST, AG-UI or queue wire shapes.** The `202` body, the AG-UI interrupt
  outcome, and `QueueMessage` attributes stay as #606 left them.
- **Thread history is still never replayed into the model.** The model's history comes from the
  session; threads remain the client-facing record, so nothing here can cause a dangling tool call
  in what the framework sees.
- **No HITL support for AG-UI threads.** `AGUIRequestHandler` is not a thread-recording surface and
  does not become one here.
- **No retention, redaction or expiry rules** for decision payloads beyond the thread store's
  existing TTL.
- **No recording of pre-runner rejections.** A `400` is not something the agent said, and writing
  one as an `assistant` message would put words in its mouth. Every failed turn already has this
  shape — a user message with no answer — so making errors visible in history is a thread-wide
  change for a separate issue, not a HITL rule.

## Worked example

One stored thread from the `planner` agent, showing a text turn, a pause, a decision the runtime
rejects, and a decision carrying words. Timestamps and ids abbreviated; `attachments: []` omitted.

```json
{"role": "user", "content": "Plan the refund for ORD-1001."}

{"role": "assistant",
 "content": {"run_id": "9f2c…", "session_id": "demo-2", "agent": "planner",
   "interruptions": [{"id": "48d8ea…", "kind": "input_required", "tool_name": null,
     "arguments": null, "message": null,
     "payload": {"question": "How should the refund be returned?",
                 "options": ["Original card", "Store credit", "Bank transfer"]}}]},
 "media_type": "application/json"}

{"role": "user",
 "content": {"resume": {"run_id": "9f2c…",
   "decisions": [{"id": "stale-id", "status": null, "message": null, "payload": "Store credit"}]}},
 "media_type": "application/json"}

{"role": "user",
 "content": {"prompt": "Use the card ending 4242 if store credit fails.",
   "resume": {"run_id": "9f2c…",
     "decisions": [{"id": "48d8ea…", "status": null, "message": null, "payload": "Store credit"}]}},
 "media_type": "application/json"}
```

- The third message names an interruption that is no longer pending: `Runtime._validate_resume`
  raises before the runner, the request answers `400`, and no assistant message follows it.
- Nothing in that message marks it as rejected — it is byte-identical in form to one that succeeded.
  Distinguishing them would require recording after the run, which the ordering requirement above
  rules out. A reader detects it as a user message with no assistant message after it.
- The thread continues with the planner's second question (another pause message) and ends with an
  ordinary text reply once the graph completes.

## Open questions

- None outstanding. All five questions raised in the first draft are resolved above: the decision
  payload's shape, a prompt sent alongside a decision, a rejected decision, a cancelled decision,
  and which example carries the DoD.

## Note on PR #817

This design was written against `develop` before #817 (`feat: a2ui threads support`, #763) merged,
and deliberately did not depend on it: it specifies `content: str | JSONPayload`, `media_type`, the
agreement validator and the wire-rendering method as its own, because a design that waits on an open
PR cannot be reviewed.

**#817 has since merged**, so the model-level requirements above arrived with it and this change is
what sits on top: the recorder's two human-in-the-loop shapes, the SSE fix, and the queue
reconstruction. The overlap resolved as expected in the three predicted files
(`integration/thread/model.py`, `integration/thread/recorder.py`, `pipeline/agent_runner.py`) plus
the two test files and two dev skills. Two details from that merge are worth reading as part of this
design rather than as merge trivia:

- **`_as_thread_message` checks `AgentPausedReplyAny` before #763's labelled-reply branch.** A
  paused reply is an `AgentReplyAny` subclass whose own `media_type` is unset, so the labelled
  branch would miss it and it would fall through to `str(result)` — the exact defect this change
  exists to fix. The A2UI post-hook only ever labels an `AgentReplyText`, so the two cannot collide
  today; the ordering is what keeps that true if it ever could.
- **`post_run`'s `media_type` parameter is #763's**, carrying a label the queue holds beside a
  labelled reply. No site in this change passes it: a pause's label comes from the branch above.
