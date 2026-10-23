# #609: Approve and reject a paused run from Slack and Telegram

A paused run currently reaches a messaging platform as the string form of its pause — there is
nothing to press, and no way back. This change gives the outbound half of the adapter seam a way to
render a pause as the platform's own interactive UI, and routes the press back through the inbound
half as an ordinary request carrying a decision. Scoped to Slack and Telegram; the seam is shared,
so the rest are per-adapter work afterwards (see
[`research/platform-interactive-ui-survey.md`](research/platform-interactive-ui-survey.md)).

## Motivation

- **A pause is flattened before any adapter sees it.** `pipeline/integration_delivery.py:103`
  delivers `AgentReplyText(response=str(body.get("result", "")))` for every reply, and
  `OutboundAdapter.deliver`'s docstring states that contract (`integration/adapter/base.py:194`).
- **The information is already on the wire.** `ResponseBuilder.build_response` promotes `status`,
  `run_id`, `agent` and `interruptions` to top-level body keys precisely so a client can branch
  without parsing `result` (`core/chat_service.py:374-380`), and a paused run is a 202
  (`core/chat_service.py:648-649`), below the `>= 400` error branch — so the body reaches
  `deliver` today and is discarded there.
- **The inbound half needs no new seam.** `InboundRequest.requests` is a
  `List[AgentRequestUnion]` (`integration/adapter/base.py:62`) and `AgentResumeRequestAny` is a
  member of that union (`core/model.py:206-216`). `Runtime` extracts the decision from the
  **request list**, not from `req.resume` (`core/runtime.py:265-271`), and `ChatService._validate`
  accepts a prebuilt non-empty list with no prompt (`core/chat_service.py:786-790`). An adapter that
  puts an `AgentResumeRequestAny` in the list resumes the run with no plumbing change.
- **Half of the per-platform work already exists.** Telegram's inbound already parses a
  `callback_query` and clears the button spinner (`integration/telegram/adapter.py:143`, `:174`,
  `:63`); Slack's outbound already posts Block Kit `blocks`
  (`integration/slack/adapter.py:265`). Neither does the other half.
- **One fix covers every host.** `IntegrationDelivery` is the single definition shared by the
  pipeline `ResponseHandler` and the serverless consumers (`pipeline/integration_delivery.py:13-22`),
  and `StreamAgentRunner` delegates integration traffic to the non-streaming path
  (`pipeline/agent_runner.py:217`), so there is exactly one body shape to handle.

```mermaid
graph LR
    P["Agent run pauses<br/>202 + interruptions"] --> D["IntegrationDelivery.deliver"]
    D -->|"deliver_paused"| A["OutboundAdapter"]
    A --> UI["Buttons in Slack / Telegram"]
    UI -->|"press"| IN["InboundAdapter.parse"]
    IN -->|"AgentResumeRequestAny<br/>in InboundRequest.requests"| Q["input queue<br/>(unchanged)"]
    Q --> R["Runtime resumes the run"]
```

## Requirements

### Delivery seam

- `IntegrationDelivery.deliver` must branch on the body's `status == "PAUSED"` before the ordinary
  text path, and reconstruct an `AgentPausedReplyAny` from the body's `run_id`, `agent`,
  `interruptions` and `session_id` keys.
  - Reconstructing the model (rather than passing the raw dict) is what keeps the content a
    validator produced, so every host delivers the same pause.
  - The `>= 400` error branch stays first and unchanged: a failed run is never a pause.
  - Issue #607 adds an equivalent reconstruction on `AgentRunner` for thread recording; when both
    have landed the two must be one helper, not two copies.
- A body that claims `PAUSED` but does not reconstruct — a missing key, a value outside its type, a
  malformed interruption, any validation failure — falls through to the ordinary text delivery with
  a logged warning, never a raise: raising costs the platform user their reply entirely.

### `OutboundAdapter` contract

- Add `deliver_paused(reply: AgentPausedReplyAny, reply_context) -> None` to `OutboundAdapter`.
  - **Concrete, not abstract.** Overriding it is how an adapter declares it can render a pause
    interactively — no capability flag, no config. The `deliver_chunk` precedent.
  - The default delivers `self.format_pause(reply)`.
- Add `format_pause(reply: AgentPausedReplyAny) -> str`: the shared rendering of a pause as readable
  text, in the shape `split_reply` already has — a text helper on the base that every adapter
  inherits and any adapter may override.
  - It names what is waiting (`tool_name`, its `arguments`, the interruption's `message`) and says
    the run is paused and waiting on a person.
  - **Its closing line is written per `kind`.** The default catches every pause, `input_required`
    among them, and that kind asks for a value rather than permission — "waiting for approval"
    would describe the wrong thing. `tool_call` and `confirmation` say approval is needed;
    `input_required` says an answer is.
  - It states **no reply instruction**. "Reply APPROVE" would only work if a typed word resolved a
    pause, and nothing maps text to a decision: the inbound adapter would build an ordinary
    `AgentRequestText`, the run would stay paused, and on Pydantic AI a fresh turn during an
    unanswered pause raises. A default that told people to do that would be instructing them to
    fail silently.
- **This is a deliberate behavioural change**, and the only one in this issue. The five adapters
  that do not override `deliver_paused` — WhatsApp, Messenger, Instagram, Teams, Gmail — stop
  delivering `str(reply)`, which is `json.dumps` of the derived content with its nulls, and start
  delivering readable text. Today's output is the "useless flattened string" the issue names; it is
  not a behaviour worth preserving byte-for-byte.
- Pluggability needs no new ABC or factory: `<platform>.outbound_adapter` already takes a dotted
  path to a replacement (`core/config.py:164-167`, `:217-220`), so a bring-your-own adapter can
  render pauses its own way.
- Rendering is scoped to the **approval** interruption kinds, `tool_call` and `confirmation`. An
  `input_required` pause has nothing a button can express and must fall through to the default text
  rendering (see Non-goals).
- Once a decision is accepted, the pause message is rewritten to drop its buttons and state what
  was decided — **what, not who**. Naming the presser is a disclosure a deployment adds by
  subclassing, not one this change assumes.
  - **The edit names the interruptions it answered**, not a bare "Approved". One press answers one
    interruption, and a pause may hold several; a message that says only "Approved" claims more
    than happened.
  - All controls go, even when interruptions remain undecided, because **a partial resume produces
    a fresh pause** rather than a run that silently drops what was not answered. Each adapter's
    `resume` applies only the supplied decisions and then re-checks: OpenAI returns
    `self._paused_reply(agent, session, result)` when `result.interruptions` is non-empty, and
    LangGraph does the same when `INTERRUPT_KEY in result`. That reply travels the ordinary output
    path and reaches `deliver_paused` again, posting its own message with its own controls.
  - So keeping the old controls up is the wrong repair: it would leave two live buttons for one
    interruption, the stale one and the new one. The edit's job is to stop claiming more than was
    decided, which is why it names the interruptions it answered.
  - This rests on an invariant the messaging UI does not own: an adapter whose `resume` completes
    while interruptions are still pending would strand them, and that would be a defect in #606's
    contract (`core/model.py:190-191`), not something a button layout can correct.
  - **The outbound half edits, not the inbound half.** The inbound adapter puts the pause message's
    coordinates into the decision turn's `reply_context`, where they cross the queue like every
    other delivery coordinate; the outbound adapter edits that message when it delivers the
    **resumed reply**, which exists only because the resume succeeded. Editing at parse time would
    clear the buttons for a decision the runtime then refused.
  - **The coordinates' presence in `reply_context` is the signal**, and the only one. `deliver`
    receives every reply the same way, so an adapter edits the pause message when the context
    carries those keys and posts normally when it does not. Nothing else distinguishes a resumed
    reply from an ordinary turn, and only the press path ever sets them.
  - `deliver_error` receives the same context and must **not** edit: a stale or rejected decision
    leaves the buttons live so the pause stays answerable.
- Collecting a reason on a denial is **per-adapter**: an adapter declares it can, or does not offer
  it. A platform that cannot must neither hold the capability back from one that can nor fake it
  with a worse mechanism — the standing no-feature-forcing rule.

### A press is an ordinary inbound request

- An inbound adapter translating a press builds `InboundRequest.requests` as a single-element list
  holding `AgentResumeRequestAny(run_id=None, decisions=[ResumeDecision(id=..., status=...)])`, and
  leaves `prompt` empty.
  - `run_id` is omitted deliberately: it is `Optional` (`core/model.py:170`) and the runtime resolves
    the run from the interruption ids, which halves what a button payload has to carry.
  - `status` is one of `approved` / `denied` / `cancelled`, limited to the verbs the adapter's
    `DECISIONS` names. `ResumeDecision.payload` stays unset for a button;
    `ResumeDecision.message` carries the refusal's reason when the platform collected one.
- The button payload carries the interruption id and the verb, and nothing else.
- `request_id` must be synthesised so that a double-press deduplicates: the platform's own press
  identifier where one exists, otherwise
  `<platform>:<conversation>:<message id>:<interruption id>:<verb>`.
  - **The interruption id is in the key because a pause can carry several interruptions**
    (`interruptions` is a list, and one turn can produce several gated tool calls). Without it,
    approving two different interruptions on the same message collides on one `dedup_id`, the
    transport discards the second, and that interruption is never answered.
  - The verb is in the key too. Pressing Approve twice is one `dedup_id` and the transport discards
    the second. Pressing Approve then Deny is two, so both reach the runtime — the first resumes,
    the second answers a pause that no longer exists and takes the 400 path above. That is the
    intended outcome, not a hole: a decision already applied must not be revisable by a later press.
  - Two presses answering *different* interruptions are serialised by the queue's per-session FIFO,
    so the second is validated against the pause the first produced rather than racing it.
- `session_id` for a press must resolve to the same conversation key the original turn used, or the
  decision reaches a session holding no pause.
- A press answering an already-resolved pause produces the runtime's `ValueError` → 400 → the
  adapter's generic `ERROR_MESSAGE`. This is accepted, not special-cased.

### Slack

- Outbound: render a pause as the existing section blocks plus one `actions` block per interruption,
  with one button per verb in `DECISIONS`, each carrying the interruption id and its verb in the
  button `value`.
- Inbound: register a Bolt action listener for `block_actions` alongside the existing
  `@app.event("message")` listener (`integration/slack/adapter.py:58`), collected through the same
  contextvar mechanism `parse` already drives.
  - **No second route.** Bolt serves events, shortcuts and interactivity on one endpoint, so the
    app's Interactivity Request URL is the same URL as its Event Subscriptions one, and
    `BUILTIN_WEBHOOK_ROUTES["slack"]` is unchanged.
  - An action listener must acknowledge within Slack's 3-second window, and
    `process_before_response=True` defers that acknowledgement until the listener returns. So it
    acknowledges **first** and works after: the denial modal below is a network call to Slack, and
    opening it before the ack spends the budget the ack needs.
- The existing `x-slack-retry-reason: http_timeout` drop (`integration/slack/adapter.py:74`) must
  continue to apply to interactive deliveries.
- Slack declares `DENY_COLLECTS_REASON = True`: a denial acknowledges, then opens a modal
  (`views.open` on the press's `trigger_id`), and the decision is built from the modal submission
  rather than the press.
  - A `view_submission` carries no channel or message context of its own, so `private_metadata`
    carries the **whole return address** — interruption id, channel, and the pause message's
    timestamp. That is what lets the submission resolve the same `session_id`, a deduplicating
    `request_id` and the same reply context a press resolves, instead of only the interruption.
  - A `views.open` that fails leaves the pause open with its buttons live, and is logged. It is not
    retried onto the queue: nothing was decided, so there is nothing to deliver.
  - A modal the user dismisses records no decision: the pause stays open and its buttons stay live.
- Once a decision is accepted, the pause message is edited to drop its `actions` block and state
  what was decided, so the outcome is visible and a second press is not invited. This is Slack's own
  pattern for a resolved interaction, not an invention.
  - **`chat.update`, not `response_url`.** The press payload carries a `response_url` that would
    replace the message with less ceremony, but it expires — roughly thirty minutes and a handful of
    uses — and our edit happens after a queue hop and a full agent resume, which is unbounded. A
    slow run, a retry or a backed-up queue would silently lose the edit and strand the buttons.
  - `chat.update` takes the channel and the message `ts`, which is exactly what `reply_context`
    already carries, needs only the bot token the adapter already holds, and has no window. It also
    works here because the pause message was posted through the adapter's ordinary
    `chat.postMessage` path; `chat.update` on a message created *via* `response_url` is reported to
    fail with `cant_update_message`.

### Telegram

- Outbound: attach an `InlineKeyboardMarkup` to the pause message; `send_message`
  (`integration/telegram/adapter.py:46`) gains an optional `reply_markup`, and nothing else changes
  for an ordinary reply.
- Inbound: `_from_callback_query` (`:174`) must produce a decision rather than text when the callback
  data is one of ours, and keep today's text behaviour for any other callback data.
- **`callback_data` is 1–64 bytes** (research), and the interruption id is the framework's own
  (`call_id`, `tool_call_id`, LangGraph's interrupt id), so its length is not Agent Kernel's to
  bound. An id that fits the budget with the prefix and verb gets buttons; one that does not falls
  back to text for that interruption, with a logged warning — no truncation, no raise, no silently
  broken button.
- `answer_callback_query` (`:63`) keeps clearing the spinner. Once the decision is accepted the
  keyboard is removed and the message edited to state what was decided, via
  `editMessageReplyMarkup` / `editMessageText` on the `message_id` the press carried.
  - Telegram publishes an editing window for messages; whether it binds a bot editing its own
    message is not established here and is confirmed while writing `spec.md`. **Telegram ships
    either way**: the edit is attempted, a refusal is logged, and the decision stands — the run has
    already resumed.
  - When the edit cannot happen, the adapter posts a short confirmation instead, so the outcome is
    visible in the chat even though the keyboard stays.
- A keyboard left live is noisy, not dangerous, and mostly not even noisy. Pressing the same button
  again produces the same `request_id`, so the transport's dedup discards it and the runtime never
  sees it. Only a different verb, or a press after the dedup window has passed, reaches the 400 path
  and costs one generic error message. A decision already applied can never be revised by a late
  press, which is the property that actually matters.
- Telegram leaves `DENY_COLLECTS_REASON` at `False` and denies with no reason: it has no modal, and
  a `force_reply` answer arrives as an ordinary message the adapter would have to correlate back to
  an interruption using state it does not hold — the problem `input_required` is scoped out for.

### Configuration

- **No new configuration, and no `enabled` flag.** Neither knob selects a backend nor carries a
  credential, which is what every messaging block in `AKConfig` holds.
- Both are **class attributes on the outbound adapter**, the shape `OutboundAdapter` already uses
  for a user-facing tunable changed by subclassing — `MESSAGE_LIMIT`, `TRUNCATION_NOTICE`,
  `ERROR_MESSAGE` (`integration/adapter/base.py:185-188`).
  - `DECISIONS: tuple[str, ...] = ("approved", "denied")` — which verbs get a button. A deployment
    wanting `cancelled` surfaced, so "nobody decided" does not read as a refusal
    (`Runner.CANCELLED_DECISION_MESSAGE`), adds it in a two-line subclass.
    - Only LangGraph carries a three-valued decision natively; the others map a cancel onto their
      framework's reject. `DECISIONS` is fixed at class definition and the serving framework is
      chosen per request, so this is **documented, not enforced**.
  - `DENY_COLLECTS_REASON: bool = False` — whether a denial collects a reason into
    `ResumeDecision.message`. A statement of what the platform can do: Slack overrides it to `True`.
- An application changes either by subclassing and pointing `slack.outbound_adapter` /
  `telegram.outbound_adapter` at the subclass.
- **The inbound half reads neither.** A plain deny button and a deny-with-reason button carry
  different action identifiers, so the press handler reacts to the button that arrived.

### Testing

- `IntegrationAdapterContract` (`integration/adapter/testing.py`) gains a case asserting that an
  adapter which does not override `deliver_paused` delivers `format_pause`'s text — readable, and
  carrying the tool name and arguments, rather than a serialised object.
- A delivery-seam test asserting a `PAUSED` body reaches `deliver_paused` with the interruptions
  intact, and a malformed `PAUSED` body falls through to text.
- Per platform: a pause renders the expected buttons; a press parses to an `AgentResumeRequestAny`
  carrying the right id and status; a press deduplicates; Telegram's over-budget id degrades to text.
- The message edit under all three outcomes: an accepted decision drops the buttons, a rejected or
  stale one leaves them live, and a duplicate press changes nothing further.
- A pause carrying two interruptions: each renders its own controls, approving one does not
  deduplicate against approving the other, the edit names only what was answered, and the remainder
  arrives as a second pause message.
- A round trip through the `in_memory` topology — pause out, press in, resume — extending
  `tests/test_integration_roundtrip.py`.

### Documentation and examples

- `docs/docs/advanced/human-in-the-loop.md` gains a section on approving from a messaging platform,
  naming what Slack and Telegram support and what the other platforms do instead, and stating the
  `cancelled` caveat: adding that button is only fully meaningful on LangGraph.
- `docs/docs/integrations/slack.md` and `telegram.md` each gain the pause rendering and its limits.
- One example demonstrating the round trip, extending an existing integration example rather than
  adding a new one.

## Non-goals

- **Teams, WhatsApp, Messenger, Instagram, Gmail, LiveKit.** No adapter outside Slack and Telegram
  is changed; all of them keep today's text delivery through the default `deliver_paused`.
- **`input_required` pauses.** A free-text answer has no button form, and correlating a later plain
  message back to an interruption is a problem this change does not solve; such a pause renders as
  text and is answered from a non-platform surface. Slack's denial modal is not an exception: it is
  opened by a press and carries its own context forward in `private_metadata`, so a modal
  submission stays correlated. What is out of scope is a plain typed message answering a pause, on
  any platform.
- **Answering a pause by typing.** `format_pause` deliberately gives no reply instruction, because
  mapping a typed "approve" onto a decision needs the session's pending pauses at the moment the
  text arrives. That belongs in a core pre-hook, applies to every surface rather than just
  messaging, and carries its own ambiguity (a person writing "approve" mid-sentence); it is a
  follow-up issue, not a fold-in here.
- **Cross-session approval.** A decision still comes from the session that paused; #610 owns the
  case where another user approves.
- **Conversation initiation.** Reaching out to a second approver is #608.
- **Streaming.** Integration traffic already takes the non-streaming path
  (`pipeline/agent_runner.py:217`); nothing in the streaming runner changes.
- **Threads.** Messaging integrations do not record conversation threads, so #607's work is not a
  dependency.

## Open questions

None outstanding. Settled in review: Slack needs no second route; a denial reason ships on Slack
and not on Telegram; neither knob is configuration; the pause message says what was decided, not
who.
