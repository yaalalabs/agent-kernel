# #609: Approve and reject a paused run from Slack and Telegram — Implementation Spec

Implements [`design.md`](design.md), which is the requirements source. Two methods are added to
`OutboundAdapter`, one branch to `IntegrationDelivery.deliver`, and an interactive half to the Slack
and Telegram adapter pairs. No new module, no new ABC, no configuration.

## Design

### `OutboundAdapter` — two new members

`ak-py/src/agentkernel/integration/adapter/base.py`, beside the existing class attributes at
`:185-188`.

```python
class OutboundAdapter(ABC):
    DECISIONS: tuple[str, ...] = ("approved", "denied")
    DENY_COLLECTS_REASON: bool = False

    def format_pause(self, reply: AgentPausedReplyAny) -> str:
        """A pause as readable text, for a platform with no interactive controls.

        Overridable like TRUNCATION_NOTICE and ERROR_MESSAGE: the wording is user-facing.
        """

    async def deliver_paused(self, reply: AgentPausedReplyAny, reply_context: Dict[str, str]) -> None:
        """A run is waiting on a human. Override to render it with the platform's controls."""
        await self.deliver(AgentReplyText(response=self.format_pause(reply)), reply_context)
```

Rules:

1. **Both are concrete.** `deliver_paused` is never abstract, so the five adapters that do not
   override it keep working untouched — the `deliver_chunk` precedent at `:205`.
2. **`format_pause` returns one string; chunking stays with `deliver`.** Both platform adapters
   already call `split_reply` inside `deliver`, so a long pause is split by the existing path and
   `MESSAGE_LIMIT` keeps its single meaning.
3. **The closing line is chosen from the kinds present, not per interruption.** A pause whose
   interruptions are *all* `input_required` closes with "waiting for an answer"; any other mix
   closes with "waiting for approval". One line per message, chosen deterministically — per-line
   wording would read as several questions when there is one message.
4. `AgentPausedReplyAny` is an `AgentReplyAny` subclass, so it is already in the `AgentReply` union
   and `deliver`'s signature needs no change.

Rendered shape (the exact text is the implementer's, this fixes the parts tests assert):

```
⏸ Waiting for approval

refund_order
  order_id: A-10294
  amount:   248.00 USD

This run is paused until someone approves it.
```

- `tool_name` on its own line; `arguments` parsed from its JSON string and listed as key/value
  pairs, falling back to the raw string when it does not parse.
- `interruption.message` is included verbatim when the framework set it.
- No reply instruction, per the design.

### `IntegrationDelivery` — the PAUSED branch

`ak-py/src/agentkernel/pipeline/integration_delivery.py`. `deliver` gains one branch after the
existing `status_code >= 400` block at `:96-102` and before the text delivery at `:103`:

```python
if body.get("status") == "PAUSED":
    paused = self._paused_reply(body, session_id)
    if paused is not None:
        run_async_sync(adapter.deliver_paused(paused, reply_context))
        self._log.info(f"[OUTPUT PAUSED] Delivered a pause to {integration}: ...")
        return
    # fall through to the ordinary text path

@staticmethod
def _paused_reply(body: dict, session_id: Optional[str]) -> Optional[AgentPausedReplyAny]:
    """Rebuild the reply from the body's promoted pause keys, or None if it does not reconstruct."""
    try:
        return AgentPausedReplyAny(
            run_id=body["run_id"],
            session_id=body.get("session_id") or session_id or "",
            agent=body["agent"],
            interruptions=[PausedInterruption(**i) for i in body["interruptions"]],
        )
    except (KeyError, TypeError, ValidationError) as e:
        ...log a warning naming the integration and the failure...
        return None
```

- `KeyError`, `TypeError` and pydantic's `ValidationError` are caught **by name**, not bare
  `Exception`: a missing key, a non-mapping interruption and a bad field value are the three ways a
  body fails to reconstruct, and a bare catch would also swallow a bug in the adapter resolved
  above.
- Returning `None` rather than raising is what makes the fall-through work; the design requires a
  malformed `PAUSED` body to be delivered as text rather than lost.
- `AgentPausedReplyAny` and `PausedInterruption` are imported at module scope beside the existing
  `AgentReplyText` import — both live in `core`, which this module already depends on. The lazy
  import rule at `:119-134` applies to `agentkernel.integration`, not to core.
- One definition serves the pipeline `ResponseHandler` and the serverless consumers, so neither
  host changes.

### Slack

`ak-py/src/agentkernel/integration/slack/adapter.py`.

**Outbound.** `SlackOutboundAdapter` sets `DENY_COLLECTS_REASON = True` and adds:

```python
async def deliver_paused(self, reply, reply_context) -> None:
    blocks = self.split_reply(self.format_pause(reply))        # existing section blocks
    for interruption in reply.interruptions:
        blocks.append(self._actions_block(interruption))        # one per interruption
    await self._client().chat_postMessage(channel=..., thread_ts=..., text="Approval needed", blocks=blocks)
```

- One `actions` block per interruption, one button per verb in `DECISIONS`.
- `value = f"{interruption.id}:{verb}"` — the payload, as the design fixes it.
- `action_id = f"{ACTION_PREFIX}{verb}"` where `ACTION_PREFIX = "ak_decision:"` — constant per verb,
  and the only thing the listener matches on. Slack documents no uniqueness rule for `action_id`;
  it documents one for `block_id`, so **`block_id = f"ak_pause:{interruption.id}"`** is what carries
  uniqueness. Two buttons sharing an `action_id` across blocks both dispatch, and the payload says
  which was pressed, so the id does not need to appear twice.
- `style` is `primary` for `approved` and `danger` for `denied`; `cancelled` is unstyled.
- A denial renders with `action_id` prefix `ak_decision_reason:` instead when
  `DENY_COLLECTS_REASON`, so the inbound half knows to open a modal from the button alone and reads
  no policy of its own.
- **The block budget is bounded explicitly.** Slack takes 50 blocks per message and 25 elements per
  actions block. `DECISIONS` holds at most three verbs, so an actions block can never overflow; the
  message can. `split_reply` contributes up to `MAX_CHUNKS + 1` section blocks (6), so at most
  `50 - len(section_blocks)` interruptions get an actions block, and any beyond that are named in
  `format_pause`'s text without controls — the same honest degradation Telegram's byte budget uses.
  A warning names how many were left unpressable.

**Inbound.** `SlackInboundAdapter.__init__` registers two more listeners beside the existing
`@self._app.event("message")` at `:58`, and a second contextvar `_decisions` collects what they
produce, drained by `parse` alongside `_events`:

```python
@self._app.action(re.compile(rf"^{ACTION_PREFIX}"))
async def _press(ack, body):
    await ack()                                   # FIRST — see below
    collected = _decisions.get(None)
    if collected is not None:
        collected.append(self._decision_from_press(body))

@self._app.action(re.compile(rf"^{REASON_PREFIX}"))
async def _press_with_reason(ack, body, client):
    await ack()
    await client.views_open(trigger_id=body["trigger_id"], view=self._reason_modal(body))

@self._app.view(MODAL_CALLBACK_ID)
async def _reason_submitted(ack, body):
    await ack()
    collected = _decisions.get(None)
    if collected is not None:
        collected.append(self._decision_from_modal(body))
```

- **The whole listener must finish inside Slack's 3 seconds**, and `ack()` ordering does not change
  that: `process_before_response=True` (`:54`) holds the HTTP response until the listener returns,
  so the budget covers everything it does — `views_open` included. `ack()` is still called first
  because Bolt requires it, but the real constraint is that a press listener does **at most one
  Slack API call and no agent work**. If that ever stops being enough the escape hatch is Bolt's
  lazy listeners; they are beta and Python-only, so nothing here depends on them.
- `parse` sets and resets both contextvars around `self._handler.handle(raw)` and concatenates the
  two lists. The existing `x-slack-retry-reason: http_timeout` short-circuit at `:74` stays first
  and therefore covers interactive deliveries too.
- `_decision_from_press(body)` builds the `InboundRequest`:

  | Field | Source | Why |
  |---|---|---|
  | `session_id` | `container.thread_ts`, else `message.thread_ts`, else `message.ts` | Must equal the `thread_ts` the original turn used (`:158`), or the decision reaches a session with no pause. The pause message is posted into that thread, so the container carries it. |
  | `request_id` | `f"slack:{channel}:{message_ts}:{interruption_id}:{verb}"` | The composite logical key. Never `action_ts`, which is minted per click. |
  | `user_id` | `user.id` | Carries the presser to `acting_user_id`, which is what lets an application's pre-hook enforce an approver policy. |
  | `group_id` | `channel.id` | Same as a message turn. |
  | `requests` | `[AgentResumeRequestAny(run_id=None, decisions=[ResumeDecision(id=..., status=verb)])]` | |
  | `prompt` | `""` | |
  | `reply_context` | `{"channel", "thread_ts", "user"}` | Identical to a message turn (`:165`), so the resumed reply lands in the same thread. |

- `_reason_modal(body)` builds a `views.open` payload whose `private_metadata` is
  `json.dumps({"interruption", "channel", "ts", "thread_ts", "user"})`. The design calls for "the
  whole return address"; `thread_ts` and `user` are in it because `reply_context` needs them and a
  `view_submission` carries no conversation of its own.
- `_decision_from_modal(body)` reads `private_metadata` back, takes the reason from the modal's
  single plain-text input, and builds the same `InboundRequest` with
  `ResumeDecision(status="denied", message=<reason>)`.

### Telegram

`ak-py/src/agentkernel/integration/telegram/adapter.py`.

**Client.** `_TelegramClient.send_message` (`:46`) gains `reply_markup: Optional[dict] = None`,
attached to the **last** chunk only, so the keyboard sits under the final message of a split reply.
Every existing caller passes nothing and sends exactly what it sends today.

**Outbound.** `TelegramOutboundAdapter.deliver_paused` renders the text through `format_pause` and
`split_reply`, and builds one keyboard row per interruption:

```python
CALLBACK_PREFIX = "akhitl:"   # not "ak:" — see below
VERB_CODES = {"approved": "a", "denied": "d", "cancelled": "c"}   # one char: the budget is 64 bytes
CALLBACK_LIMIT = 64

data = f"{CALLBACK_PREFIX}{VERB_CODES[verb]}:{interruption.id}"
if len(data.encode()) > CALLBACK_LIMIT:
    ...warn, naming the interruption and the byte count; render no row for it...
```

- **The prefix is `akhitl:`, not `ak:`.** An Agent Kernel application may already ship its own
  inline keyboards, and a two-letter prefix would hijack its presses into decisions — behavioural
  change 2 below is scoped by exactly this string. The extra four bytes are affordable: the
  prefix, verb code and separators cost 9, leaving 55 for an interruption id (an OpenAI `call_id`
  is about 29, a LangGraph interrupt id about 32).
- The budget is checked in **bytes**, not characters.
- `VERB_CODES` is a wire format: a code is never reused for another verb, because a message can
  outlive the deploy that rendered it.
- An over-budget interruption contributes no row; the others still get theirs, and the message
  appends `UNPRESSABLE_NOTICE` naming its id. The notice is required, not cosmetic: `format_pause`
  shows an id only when the framework named nothing else, so without it two gated calls to the same
  tool are indistinguishable and the reader cannot tell which one has no buttons.
- If no interruption fits, the message is sent with no `reply_markup` and is exactly the default
  text delivery.

**Inbound.** `_from_callback_query` (`:174`) branches on the prefix:

- Data starting with `CALLBACK_PREFIX` → a decision request. Data that does not → today's path
  unchanged, including `_build`'s `request_id=str(update_id)`.
- The decision request overrides `request_id` with
  `f"telegram:{chat_id}:{message_id}:{interruption_id}:{verb}"`. **This is the behavioural fix the
  design requires**: today `_build` sets `request_id=str(update_id)` (`:209`), and `update_id` is
  minted per update, so two presses of the same button already produce two different ids and
  neither dedupes.
- `session_id` stays `str(chat_id)` and `user_id` stays `callback_query.from.id`, both unchanged
  from `_build`.
- `answer_callback_query` (`:63`) keeps clearing the spinner and is still called before anything
  else, including for data that is not ours.
- A decision request bypasses `_build`: that helper appends an `AgentRequestText` and runs
  `AttachmentStorageManager.offload`, neither of which applies to a decision.

### Consumer changes

| Consumer | Change |
|---|---|
| `pipeline/response_handler.py` | None. It calls `IntegrationDelivery.deliver`, which now branches internally. |
| Serverless consumers (`deployment/aws/serverless/`) | None, same reason. |
| `AgentRunner` / `StreamAgentRunner` | None. `StreamAgentRunner` already delegates integration traffic to the non-streaming path (`pipeline/agent_runner.py:217`). |
| WhatsApp, Messenger, Instagram, Teams, Gmail adapters | None. They inherit `deliver_paused`, and the text they deliver for a pause changes (see Behavioural changes). |

### Config changes

**None.** No new `AKConfig` field, no new block, no `enabled` flag. `DECISIONS` and
`DENY_COLLECTS_REASON` are class attributes changed by subclassing, mounted through the existing
`slack.outbound_adapter` / `telegram.outbound_adapter` dotted paths (`core/config.py:164-167`,
`:217-220`). Existing YAML and `AK_*` variables are unaffected.

### Behavioural changes

1. **A pause delivered to a non-overriding adapter changes text.** WhatsApp, Messenger, Instagram,
   Teams and Gmail stop receiving `str(reply)` — `json.dumps` of the derived content including its
   nulls — and receive `format_pause`'s text. Intentional; the design names it as the only one.
2. **A Telegram press whose callback data starts with `akhitl:` no longer reaches the agent as a
   prompt.** It becomes a decision. Data not matching the prefix is unchanged, so an application
   that already ships its own inline keyboards keeps working — which is why the prefix is specific
   rather than short.
3. **A Telegram press's `request_id` changes shape** from `update_id` to the composite key, for
   our presses only. This is what makes a repeat press deduplicate.
4. **Slack now produces requests from `block_actions` and `view_submission` deliveries.** Today
   Bolt dispatches them to no listener and `parse` returns an empty list.

**Non-changes:** ordinary message delivery on both platforms, attachment handling, verification,
`BUILTIN_WEBHOOK_ROUTES`, every other adapter's `deliver`, `AgentReply` and its union, and the
`reply_context` keys each platform already sets.

## Error handling

| Failure | Behaviour |
|---|---|
| `PAUSED` body does not reconstruct | Warning naming the integration; delivered as ordinary text. Never raises — a raise costs the user their reply. |
| `views.open` fails | Logged. No request is enqueued, so the pause stays open with its buttons live. Not retried: nothing was decided. |
| Modal dismissed | No `view_submission`, so no decision. Pause unchanged. |
| `callback_data` over 64 bytes | Warning naming the interruption and byte count; that interruption renders without a row. |
| Press payload malformed (no parsable `value` / callback data) | Logged, contributes no request. An unparsable press is an ignorable delivery, not an error. |
| Verb not in `DECISIONS` | Rejected at parse with a warning, no enqueue. Reachable when a message outlives a subclass change. |
| Press answering a resolved pause | `Runtime` raises `ValueError` → 400 → `deliver_error` with the generic `ERROR_MESSAGE`. Unchanged path. |
| Platform send fails in `deliver_paused` | Propagates, as `deliver` does: the consumer retries and then calls `deliver_error`. |

## Testing

Run with `cd ak-py && uv run pytest`.

**`tests/test_integration_adapter_contract.py`** — one case added to `IntegrationAdapterContract`
(`integration/adapter/testing.py`), so every platform subclass inherits it: an adapter that does not
override `deliver_paused` delivers `format_pause`'s text, and that text contains the tool name and
is not `str(reply)`. The contract builds a two-interruption `AgentPausedReplyAny` fixture.

**`tests/test_pipeline_integration_delivery.py`** — extends the existing file:
- a `PAUSED` body reaches `deliver_paused` with its interruptions intact;
- each malformed shape (missing `run_id`, `interruptions` not a list, a `kind` outside the Literal)
  falls through to `deliver` with the body's `result` text and logs a warning;
- a `status_code >= 400` body still takes `deliver_error` even when it carries `status: "PAUSED"`.

**`tests/test_slack_integration.py`** — extends the existing file, which builds the adapter via
`object.__new__` with a stubbed client:
- `deliver_paused` posts section blocks plus one `actions` block per interruption, with the expected
  `value` and `action_id`;
- `DECISIONS` of three verbs renders three buttons;
- a `block_actions` payload parses to one `InboundRequest` carrying `AgentResumeRequestAny`, the
  thread-derived `session_id`, the composite `request_id` and `user.id` as `user_id`;
- a denial press opens a modal and enqueues nothing; the `view_submission` that follows carries the
  reason into `ResumeDecision.message` and reconstructs the context from `private_metadata`;
- `ack` is awaited before `views_open` (assert call order on the stub).

**`tests/test_telegram_integration.py`** — extends the existing file:
- `deliver_paused` sends `reply_markup` on the last chunk only;
- an over-budget interruption renders no row while its siblings do, and an all-over-budget pause
  sends no `reply_markup` at all;
- a `callback_query` carrying `akhitl:a:<id>` parses to a decision with the composite `request_id`,
  while one carrying other data keeps today's text behaviour and its `update_id` request id.

**`tests/test_integration_roundtrip.py`** — extends the existing `in_memory` round trip: a paused
reply out, a press in, and the resumed reply delivered. Also the two multi-interruption properties
the design calls for — approving one interruption does not deduplicate against approving the other,
and two decisions delivered in order both land. Deliberately not a multi-worker concurrency test.

**Dedup**, asserted against a real `InMemoryTransport` rather than only at the key: two presses of
the same button enqueue through `IntegrationProducer` and only one message is fetched, while a
press of a *different* verb or a *different* interruption on the same message yields two. The
contract's `test_the_queue_hop_preserves_the_reply_context` already pins the
`f"{name}:{request_id}"` dedup_id shape this relies on.

## Documentation

Per the design: `docs/docs/advanced/human-in-the-loop.md`, `docs/docs/integrations/slack.md` and
`telegram.md`, plus one example extending an existing integration example. The Slack page must
carry the app-side setup — Interactivity & Shortcuts enabled with its Request URL set to the events
URL — and both pages must state that anyone who can see the message can press the button.
