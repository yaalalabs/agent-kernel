# Interactive approval UI, per messaging platform

Survey for issue #609 — "messaging integrations present pending approvals and accept
approve/reject in a usable UX". Two questions per platform: what interactive UI the platform
offers for a yes/no decision, and how much of it Agent Kernel's adapter pair already does.

## Verification status

- **[code]** — read from this repo on `develop` at `ddf65964` while writing this survey. Line
  references are to that commit.
- **[docs]** — read from the platform's documentation during this survey.
- **[unverified]** — believed true, not checked. Confirm before the design depends on it.

---

## Summary

| Platform | Interactive UI | Inbound press already parsed? | Outbound buttons today? | Fit |
|---|---|---|---|---|
| **Slack** | Block Kit `actions` + buttons | No — only `message` events | Posts `blocks`, text only | **Strong — first target** |
| **Telegram** | Inline keyboard | **Yes** — `callback_query` data retyped as the prompt | No `reply_markup` | **Strong — cheap second** |
| **WhatsApp** | Interactive reply buttons (max 3) | **Yes** — but reads the title, not the id | `type: text` only | **Good — follow-up** |
| **Teams** | Adaptive Card `Action.Submit` | No — the activity is dropped | Text only | **Good, highest cost** |
| **Messenger** | Quick replies / button template | **Yes** — `postback` handled | Text only | Workable |
| **Instagram** | Quick replies (thinner than Messenger) | **Yes** — `postback` handled | Text only | Weak |
| **Gmail** | None usable | n/a (poller) | n/a | **Out of reach** — text reply only |
| **LiveKit** | None (voice) | n/a | n/a | **Out of reach** — spoken confirmation |

The recurring shape: **four adapters already parse a button press inbound, and all four lose the
structured decision** — the agent sees an ordinary turn. They lose it two different ways, which
matters for how much each is worth fixing:

- **The identifier is discarded.** WhatsApp and the two Meta platforms read the press's *display
  title* and drop the id that says which option it was.
- **The identifier survives but is retyped.** Telegram passes the callback data straight through as
  the prompt text, so the value is intact and only its meaning is lost.

The missing half is outbound — no adapter sends anything but text — plus routing a press to a
decision rather than to a prompt.

---

## What is shared, and paid for once

Whichever platform goes first carries the seam work:

- **The flattening.** `pipeline/integration_delivery.py:103` delivers
  `AgentReplyText(response=str(body.get("result", "")))` — the "useless flattened string" the
  issue names. The output-queue body already carries `status: PAUSED`, `run_id` and
  `interruptions` as promoted keys (from #606), so the information is there; nothing reads it.
  **[code]**
- **The contract.** `OutboundAdapter.deliver`'s docstring states the reply always arrives as an
  `AgentReplyText` (`integration/adapter/base.py:194`). A pause has to reach the adapter as
  something richer, opt-in, so adapters that render no buttons keep working unchanged. **[code]**
- **What a button has to carry.** `ResumeSpec.run_id` is `Optional` (`core/model.py:170`) — the
  runtime resolves the run from the interruption ids. So a button payload needs only the
  interruption id plus a `status` of `approved` / `denied` / `cancelled`
  (`ResumeDecision`, `core/model.py:156-159`). That is what keeps the tightest payload budget
  below viable. **[code]**

---

## Slack — first target

Outbound already posts Block Kit: `deliver` sends `blocks=self.split_reply(str(reply))`
(`integration/slack/adapter.py:265`), so an `actions` block with Approve/Deny buttons is an
addition to an existing shape rather than a new one. **[code]**

Inbound registers one listener, `@self._app.event("message")`
(`integration/slack/adapter.py:58`), and `parse` runs Bolt's dispatch and hands Bolt's own
response back. A button press arrives as a `block_actions` interactive payload, so the work is
an `@app.action` listener beside the message one. **[code]**

Open question: whether Slack's interactivity Request URL can point at the same webhook path the
events subscription uses, and whether `AsyncSlackRequestHandler` dispatches both without extra
configuration. Believed yes. **[unverified]**

## Telegram — cheap second

Inbound is **already done**. `parse` branches on `callback_query`
(`integration/telegram/adapter.py:143`), `_from_callback_query` turns the press into a request
and even clears the button's loading spinner via `answer_callback_query`
(`:174`, `:63`). Today it uses the callback data *as the message text*; HITL needs it routed to
a decision instead. **[code]**

Outbound sends text only — `send_message` takes `chat_id` and chunks, with no `reply_markup`
(`integration/telegram/adapter.py:46`, `:308`). **[code]**

**The one real constraint.** `callback_data` is UTF-8, 1–64 bytes. An interruption id (the
framework's own id) plus a verb may not fit, and the limit counts bytes, so a multibyte
character costs more than one. The standard workaround is to put a short key in the callback
data and hold the real payload server-side — AK has a session store to hold it in.
**[docs — from python-telegram-bot's reference, which mirrors the Bot API; the official
core.telegram.org page was not fetched]**

## WhatsApp — follow-up

Inbound already parses interactive replies: `_to_request` branches on `message_type ==
"interactive"` and handles both `button_reply` and `list_reply`
(`integration/whatsapp/adapter.py:177-182`). It takes `.get("title")` — the *display text* —
where HITL wants `.get("id")`. Switching that one read gives correlation for free. **[code]**

Outbound sends `{"type": "text"}` (`integration/whatsapp/adapter.py:57`), so an interactive
message shape is new work in the client. **[code]**

Limits: **3 reply buttons maximum**, button **id up to 256 characters**, body up to 1024
**[docs — Meta]**; button **title 20 characters** and titles must be unique **[docs —
third-party only; not found on Meta's own page]**. Three buttons is enough for
approve/deny/cancel exactly, with nothing left over.

## Teams — good fit, highest cost

Adaptive Cards are the native approval UI, and `Action.Submit` with an **object** `data` payload
sends an invisible message activity: `value` is populated and `text` is left empty. **[docs]**

That is exactly what AK's inbound currently drops — `_to_request` returns `None` for a
non-message activity (`integration/teams/adapter.py:181`) and again when there is no text and no
attachments (`:188`). So the inbound branch is new, and the outbound side needs a card builder.
**[code]**

Cost rather than difficulty is what sets this apart: the Teams adapter is the largest of the
family (546 lines) and carries Bot Framework machinery — tenant resolution, token acquisition,
the Bot Connector — and it is the hardest to exercise without a real tenant.

## Messenger and Instagram

Both already normalise a `postback` into text, using the title and falling back to the payload,
and both synthesise a request id from the sender plus the payload because a postback carries no
message id (`integration/messenger/adapter.py:96-104`,
`integration/instagram/adapter.py:103-111`). Outbound is text only on both. Instagram's button
support is the thinner of the two, which is what puts it last. **[code]**

## Gmail and LiveKit — out of reach

Gmail is a `PollingInboundAdapter` (`integration/gmail/adapter.py:159`) over email. There is no
button a bot can put in a message that a recipient can press back into the pipeline, so the best
available UX is "reply with APPROVE" — which is the flattened-string experience the issue exists
to remove. **[code]**

LiveKit is realtime voice. A decision is spoken, not pressed; it needs an intent-recognition path
rather than an interactive-UI one, which is a different piece of work.

---

## Recommendation

**Slack and Telegram in #609.** Slack satisfies the DoD's named integration and pays for the
shared seam; Telegram's inbound half already exists, and both are testable without a tenant or a
business account — which is what makes them the pair to prove the seam with.

**WhatsApp and Teams after**, against a seam that is already designed and exercised twice. Note
that no issue covers them today: #608 is conversation initiation and #610 is cross-session
approval, so a follow-up task has to be filed.

Nothing technical forces this split. #609's DoD says "at least one integration (Slack)", a floor
rather than a cap; the split is a judgement about effort and testability.

## Sources

- Telegram, `callback_data` 1–64 bytes: https://docs.python-telegram-bot.org/en/v22.6/telegram.inlinekeyboardbutton.html
- WhatsApp interactive reply buttons: https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/interactive-reply-buttons-messages
- Teams card actions, `Action.Submit` payload shape: https://learn.microsoft.com/en-us/microsoftteams/platform/task-modules-and-cards/cards/cards-actions
