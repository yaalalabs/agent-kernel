# #609: Approve and reject a paused run from Slack and Telegram — Implementation Plan

Six iterations. Order is deliberate: the shared seam lands first and is useful on its own (five
adapters stop emitting JSON), then Telegram proves the override cheaply, then Slack's buttons, then
Slack's modal — the riskiest piece, and the one the branch is shippable without.

Run `cd ak-py && uv run pytest` throughout; `make lint-check` before each commit.

## Iteration 1: The delivery seam

- **Goal:** a paused run reaches every messaging adapter as readable text instead of
  `json.dumps` of the reply. No platform renders buttons yet.
- **Files:** `ak-py/src/agentkernel/integration/adapter/base.py`,
  `ak-py/src/agentkernel/pipeline/integration_delivery.py`,
  `ak-py/src/agentkernel/integration/adapter/testing.py`,
  `ak-py/tests/test_pipeline_integration_delivery.py`
- **Steps:**
  1. Add `DECISIONS`, `DENY_COLLECTS_REASON`, `format_pause` and `deliver_paused` to
     `OutboundAdapter` (spec *"`OutboundAdapter` — two new members"*), including the per-kind
     closing line.
  2. Add the `status == "PAUSED"` branch and `_paused_reply` to `IntegrationDelivery.deliver`
     (spec *"`IntegrationDelivery` — the PAUSED branch"*), catching `KeyError`/`TypeError`/
     `ValidationError` by name and falling through on failure.
  3. Add the contract case to `IntegrationAdapterContract` so all seven platform subclasses
     inherit it.
  4. Extend the delivery-seam tests: intact pause, each malformed shape, and `>= 400` still
     taking `deliver_error`.
- **Verify:** `uv run pytest tests/test_pipeline_integration_delivery.py tests/test_integration_adapter_contract.py`
- **Behavioural change lands here** — the one the spec lists. Worth its own commit so it is
  bisectable.

## Iteration 2: Telegram

- **Goal:** a pause renders an inline keyboard in Telegram and a press resumes the run.
- **Files:** `ak-py/src/agentkernel/integration/telegram/adapter.py`,
  `ak-py/tests/test_telegram_integration.py`
- **Steps:**
  1. `_TelegramClient.send_message` gains `reply_markup`, attached to the last chunk only.
  2. `TelegramOutboundAdapter.deliver_paused` builds one row per interruption with the
     `akhitl:` prefix, skipping any whose `callback_data` exceeds 64 **bytes**.
  3. `_from_callback_query` branches on the prefix: ours becomes an `AgentResumeRequestAny` with
     the composite `request_id`; anything else keeps today's path, `str(update_id)` included.
  4. Tests: keyboard on the last chunk, over-budget interruption degrades while siblings render,
     prefix match produces a decision, non-prefix data unchanged.
- **Verify:** `uv run pytest tests/test_telegram_integration.py -k "pause or callback"`
- Telegram first because its inbound half already exists, so this exercises the seam end to end
  for the least new code.

## Iteration 3: Slack buttons

- **Goal:** approve and deny from Slack. No reason modal yet.
- **Files:** `ak-py/src/agentkernel/integration/slack/adapter.py`,
  `ak-py/tests/test_slack_integration.py`
- **Steps:**
  1. `SlackOutboundAdapter.deliver_paused`: section blocks from `split_reply(format_pause(...))`
     plus one actions block per interruption, with `value`, the constant `action_id` and the
     unique `block_id` (spec *"Slack"*). Apply the 50-block cap.
  2. Add the `_decisions` contextvar and the `@app.action` listener; drain it in `parse` beside
     `_events`.
  3. `_decision_from_press` builds the `InboundRequest` per the spec's field table — thread-derived
     `session_id`, composite `request_id`, `user.id` as `user_id`.
  4. Tests: block shape, three-verb `DECISIONS`, a `block_actions` payload parsing to a decision.
- **Verify:** `uv run pytest tests/test_slack_integration.py`
- **Keep the listener to one Slack API call.** The 3-second budget covers the whole listener under
  `process_before_response=True`; this is where that rule is easiest to break.

## Iteration 4: Slack denial modal

- **Goal:** denying in Slack collects a reason into `ResumeDecision.message`.
- **Files:** `ak-py/src/agentkernel/integration/slack/adapter.py`,
  `ak-py/tests/test_slack_integration.py`
- **Steps:**
  1. Set `DENY_COLLECTS_REASON = True` and render the deny button with the
     `ak_decision_reason:` prefix.
  2. Add the `@app.action` listener that opens the modal and the `@app.view` listener that
     consumes the submission; `private_metadata` carries interruption, channel, ts, thread_ts and
     user.
  3. `_decision_from_modal` rebuilds the context and sets `ResumeDecision.message`.
  4. Tests: the press opens a modal and enqueues nothing; the submission carries the reason and
     reconstructs the context; a dismissed modal records nothing.
- **Verify:** `uv run pytest tests/test_slack_integration.py -k "modal or reason"`
- Last because it is the riskiest against the 3-second budget and the branch is useful without it.

## Iteration 5: Cross-cutting tests

- **Goal:** the properties no single adapter owns.
- **Files:** `ak-py/tests/test_integration_roundtrip.py`
- **Steps:**
  1. Round trip over `in_memory`: pause out, press in, resumed reply delivered.
  2. Two presses of the same button enqueue one message through a real `InMemoryTransport`; a
     different verb or a different interruption enqueues two.
  3. A two-interruption pause: separate controls, no cross-dedup, the remainder arrives as a
     second pause message.
  4. Two decisions on one session delivered in order both land. **Not** a multi-worker concurrency
     test — that asserts the pipeline's guarantee, which this issue does not change.
- **Verify:** `uv run pytest tests/test_integration_roundtrip.py`

## Iteration 6: Sync docs and skills

- **Goal:** no guidance left describing the old contract.
- **Files and the specific lines that go stale:**
  - `.agents/skills/ak-dev-new-messaging-integration/SKILL.md:176` — "The reply always arrives as
    an `AgentReplyText`" is no longer true for a pause. Also the `OutboundAdapter` sketch around
    `:148-178` and the checklist at `:322`.
  - `.agents/skills/ak-dev-architecture/SKILL.md:552` — the `OutboundAdapter` member list
    (`deliver`, `deliver_error`, `acknowledge`, `split_reply`) needs `deliver_paused` and
    `format_pause`; the flow line at `:539` still reads `-> OutboundAdapter.deliver`.
  - `docs/docs/advanced/human-in-the-loop.md` — approving from a messaging platform, what Slack and
    Telegram support, what the others do instead, the `cancelled` caveat, and that anyone who can
    see the message can press.
  - `docs/docs/integrations/slack.md` — the app-side setup: Interactivity & Shortcuts enabled with
    its Request URL set to the events URL.
  - `docs/docs/integrations/telegram.md` — the pause rendering and the 64-byte limit.
  - `examples/api/slack/` — the example this change demonstrates in. Its `server.py` is already
    `IOHandler.run(handlers=[WebhookRESTRequestHandler(SlackInboundAdapter())])`, so the only code
    change is one tool declared with `needs_approval=True` (OpenAI's gating flag, already carried
    by `OpenAIToolBuilder.bind(**options)`) to make the agent pause. No new files.
  - `examples/api/slack/README.md` — **the setup half, which the buttons do not work without**:
    enable Interactivity & Shortcuts in the Slack app and set its Request URL to the same URL as
    Event Subscriptions. Without it the pause renders and the press goes nowhere.
  - `examples/api/telegram/` has the identical shape if a second demo is wanted later; this change
    ships one.
  - **Not** `examples/api/hitl/` — that is the REST/AG-UI surface #606 shipped, and it carries the
    card-retirement bug named in the follow-up below. Mixing a messaging demo into it would blur
    what each example is for.
- **Verified as needing no change:** `ak-dev-testing-conventions` (the contract suite row still
  describes it accurately), `BUILTIN_WEBHOOK_ROUTES` and the webhook-route docs (no new route),
  `core/config.py` and every config reference (no new field).
- **Verify:** run the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` flows
  before merge, and `make lint-check-all`.

## Follow-ups to file (not part of this branch)

- A "decision was applied" marker in the response body — the #606 gap that blocks editing the pause
  message, with `examples/api/hitl/frontend/src/App.tsx:53-64` as the existing victim.
- A per-session resume lease, or a compare-and-set session write, for the pipeline.
