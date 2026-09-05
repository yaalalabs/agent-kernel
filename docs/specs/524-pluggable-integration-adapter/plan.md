# #524: Pluggable request/response adapter for messaging integrations — Implementation Plan

Ten iterations. Iterations 1–4 add seams without removing anything, so the branch stays green
throughout; the seven handler classes only disappear in iterations 5–7, and each of those
iterations rewrites its own platform's tests so the suite never goes red between iterations.

## Iteration 1: Core and pipeline seams

- **Goal:** a prebuilt `AgentRequest` list survives the queue hop, integration attributes survive
  the runner hop, and the shared enqueue / async-bridge / attachment-offload helpers exist. No
  adapters yet.
- **Files:** `core/model.py`, `core/chat_service.py`, `core/util/async_bridge.py` (new),
  `core/multimodal/storage/offload.py` (new), `integration/thread/manager.py`,
  `pipeline/envelope.py`, `pipeline/producer.py` (new), `pipeline/request_handler.py`,
  `pipeline/agent_runner.py`, `pipeline/__init__.py`
- **Steps:**
  1. `AgentRequestUnion` + `BaseRunRequest.requests`; add `"requests"` to
     `RequestBuilder._attach_additional_context`'s `known_fields` (spec §4).
  2. `requests=` parameter on `ChatService.process_chat_request` / `process_stream_chat_sync`,
     forwarded to `execute_sync` / `execute_stream_sync` (spec §4).
  3. `run_async_sync` in `core/util/async_bridge.py`; `AgentHandler._run_async_sync` delegates to
     it (spec §6).
  4. `offload_attachments` + `StoredAttachment` extracted from
     `ConversationThreadManager.store_attachments`, which keeps its signature, return type and
     error wording (spec §8).
  5. `ATTR_INTEGRATION` and `REPLY_CONTEXT_PREFIX` in `pipeline/envelope.py` (spec §2).
  6. `RequestProducer`; `RestHandler._enqueue_request` delegates to it (spec §3).
  7. `_FORWARDED_ATTRIBUTES` predicate; `StreamAgentRunner.process` /`.on_permanent_failure`
     delegate to the non-streaming path on `ATTR_INTEGRATION`; both runners pass
     `requests=body.requests` (spec §5).
- **Verify:** `uv run pytest tests/test_pipeline_agent_runner.py tests/test_pipeline_request_handler.py
  tests/test_chat_service_core.py tests/test_model.py tests/test_thread_manager.py` — all green
  with no edits (this iteration is behaviour-preserving for existing paths).

## Iteration 2: The adapter package

- **Goal:** the ABCs, envelope, factory and producer exist and are unit-testable against a fake
  adapter pair.
- **Files:** `integration/adapter/{__init__,base,factory,producer,testing}.py` (all new)
- **Steps:**
  1. `base.py`: `Source`, `InboundRequest`, `InboundParseResult`, `InboundAdapter`,
     `PollingInboundAdapter`, `OutboundAdapter` incl. the base `split_reply` (spec §1).
  2. `factory.py`: `IntegrationAdapterFactory.create_outbound` with the three-step resolution and
     the lock-guarded instance cache (spec §1).
  3. `producer.py`: `IntegrationProducer` over `RequestProducer`, attribute stamping and the 8 KB
     budget check (spec §1).
  4. `testing.py`: `IntegrationAdapterContract` skeleton (spec §12 / Testing).
- **Verify:** `uv run pytest tests/test_integration_adapter_factory.py tests/test_integration_producer.py`

## Iteration 3: Hosting

- **Goal:** an adapter can be mounted and polled; mounting it outside a pipeline topology fails
  fast.
- **Files:** `integration/adapter/webhook.py` (new), `integration/adapter/poller.py` (new),
  `api/handler.py`, `api/http.py`, `pipeline/io_handler.py`
- **Steps:**
  1. `WebhookRESTRequestHandler` (routes, verify → parse → acknowledge → enqueue → response)
     (spec §7).
  2. `RESTRequestHandler.requires_pipeline = False`; the `RESTAPI.run` check after the delegation
     branch and outside the `cls is RESTAPI` guard (spec §7).
  3. `PollerRunner` with the `in_memory` rejection and the `shutdown_event`-sliced loop (spec §7).
  4. `IOHandler.run(..., pollers=None)`: peer threads on `in_memory`, warning on a broker
     transport (spec §7).
- **Verify:** `uv run pytest tests/test_integration_webhook_handler.py
  tests/test_integration_poller_runner.py tests/test_api_http.py tests/test_pipeline_io_handler.py`

## Iteration 4: Response Handler dispatch and config

- **Goal:** an output message carrying `integration` reaches an outbound adapter; every platform
  block accepts an outbound override.
- **Files:** `pipeline/response_handler.py`, `core/config.py`
- **Steps:**
  1. The `ATTR_INTEGRATION` branch ahead of the mode branch, the status-based
     `deliver` / `deliver_error` split, and the same branch in `on_permanent_failure` (spec §6).
  2. `outbound_adapter: str = ""` on the seven platform config classes (spec, Config changes).
- **Verify:** `uv run pytest tests/test_pipeline_response_handler.py tests/test_config.py`

## Iteration 5: Slack and Teams adapters

- **Goal:** the two SDK-owned-response platforms work end to end; their handler classes are gone.
- **Files:** `integration/slack/adapter.py` (new), `integration/slack/__init__.py`,
  `integration/teams/adapter.py` (new), `integration/teams/__init__.py`; **delete**
  `integration/slack/slack_chat.py`, `integration/teams/teams_chat.py`; rewrite
  `tests/test_slack_integration.py`, `tests/test_teams_integration.py`
- **Steps:** port each platform's parse/deliver/acknowledge per spec §9, including Slack's block
  `split_reply` override and ack `chat_update`, and Teams' serialized `ConversationReference` +
  `continue_conversation` delivery.
- **Verify:** `uv run pytest tests/test_slack_integration.py tests/test_teams_integration.py`

## Iteration 6: WhatsApp, Messenger, Instagram, Telegram adapters

- **Goal:** the four separable-verification platforms work end to end.
- **Files:** `integration/{whatsapp,messenger,instagram,telegram}/adapter.py` (new) and their
  `__init__.py`; **delete** the four `<platform>_chat.py` modules; rewrite
  `tests/test_whatsapp_integration.py`; **new** `tests/test_messenger_integration.py`,
  `tests/test_instagram_integration.py`, `tests/test_telegram_integration.py` (these three have no
  test file today)
- **Steps:** port `verify` (HMAC / secret token), `challenge` (Meta `hub.challenge`), batched
  `parse`, acknowledge (typing / mark-seen / ack text) and `deliver` per spec §9; Telegram parses
  the whole update object.
- **Verify:** `uv run pytest tests/test_whatsapp_integration.py tests/test_messenger_integration.py
  tests/test_instagram_integration.py tests/test_telegram_integration.py`

## Iteration 7: Gmail poller adapter

- **Goal:** the only `PollingInboundAdapter` works end to end under `PollerRunner`.
- **Files:** `integration/gmail/adapter.py` (new), `integration/gmail/__init__.py`; **delete**
  `integration/gmail/gmail_chat.py`; rewrite `tests/test_gmail_integration.py`
- **Steps:** `poll()` (unread query + sender/subject filters + the retained `_processed_emails`
  guard), `parse()` (thread history, attachments, offload), `deliver()` (threaded reply, signature,
  then mark-as-read), `mark_handled()` (spec §9).
- **Verify:** `uv run pytest tests/test_gmail_integration.py tests/test_integration_poller_runner.py`

## Iteration 8: Tests

- **Goal:** the cross-cutting suites `spec.md`'s Testing section requires, beyond the per-platform
  rewrites already landed in iterations 5–7.
- **Files:** `tests/test_integration_adapter_contract.py`, `tests/test_integration_roundtrip.py`,
  `tests/test_attachment_offload.py` (new); edits to `tests/test_pipeline_agent_runner.py`,
  `tests/test_pipeline_response_handler.py`, `tests/test_pipeline_request_handler.py`,
  `tests/test_pipeline_io_handler.py`, `tests/test_api_http.py`, `tests/test_config.py`,
  `tests/test_model.py`, `tests/test_chat_service_core.py`
- **Steps:** subclass `IntegrationAdapterContract` once per built-in adapter; add the
  `in_memory` round-trip (platform event → agent → recording outbound adapter, and the ≥ 400 →
  `deliver_error` path); add the offload-guard tests; extend the pipeline files with the
  forwarding, STREAM-delegation, dispatch-ordering and `requires_pipeline` assertions listed in
  `spec.md`'s Testing section.
- **Verify:** `cd ak-py && uv run pytest tests/`

## Iteration 9: Consumers — examples and the e2e app

- **Goal:** every in-repo consumer of the deleted classes is migrated. The `ak-k8s` chart is out of
  scope (design Non-goals): webhook adapters ride the existing io tier, and the poller tier's
  Deployment is a follow-up CR.
- **Files:** `examples/api/{slack,whatsapp,messenger,instagram,telegram,teams,gmail}/server.py`
  and their `config.yaml`; `examples/api/messenger/example_custom_handler.py`,
  `examples/api/whatsapp/example_custom_handler.py`; `e2e/app/app.py`
- **Steps:**
  1. `RESTAPI.run([...])` → `IOHandler.run(handlers=[WebhookRESTRequestHandler(...)])` in the six
     webhook examples; the Gmail example becomes `IOHandler.run(pollers=[PollerRunner(...)])`.
  2. `e2e/app/app.py`: same migration, keeping `_append_optional`'s partial-credential
     degradation (spec, Consumer changes).
  3. The two `example_custom_handler.py` files subclass the inbound adapter and override `parse`.
- **Verify:** `uv run pytest tests/` still green; each example's `server_test.py` where one exists.

## Iteration 10: Sync docs and skills

Surfaces this change invalidates. Each is named with the line that goes stale; run the
`ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` flows before merge to confirm
nothing else moved.

- `.agents/skills/ak-dev-new-messaging-integration/SKILL.md` — **rewritten**. The whole skill
  describes writing a `RESTRequestHandler` subclass that calls `ChatService.execute` inline
  (`SKILL.md:19-30`); it becomes "write an `InboundAdapter`/`OutboundAdapter` pair".
- `.agents/skills/ak-dev-architecture/SKILL.md` — the chat-execution-layering diagram's `MSG` node
  (`:153`, messaging integrations now enter through the queue, not `ChatService` directly); the
  plugin-architecture list (`:30`, the new factory); the config-sections list (`:216`); the
  directory tree (`:700-714`, `integration/adapter/`); the `RESTAPI.run` activation rule
  (`:584-591`, the new `requires_pipeline` check); the pipeline component table
  (`io_handler.py` row: `pollers`; `agent_runner.py` row: the new forwarded attributes and the
  STREAM delegation; `response_handler.py` row: the dispatch branch); `:971`.
- `ak-py/src/agentkernel/skills/ak-add-integration/SKILL.md` — every `RESTAPI.run([Agent<X>RequestHandler()])`
  snippet (`:68-72`, `:114-118`, `:159-163`, `:202-205`, `:239-242`, `:282-285`, `:319-322`).
- `docs/docs/integrations/{overview,slack,whatsapp,messenger,instagram,telegram,teams,gmail}.md` —
  mounting snippets, the new `outbound_adapter` config field, the `multimodal.enabled` requirement
  for attachments, and the Gmail poller topology.
- `docs/docs/deployment/onprem-kubernetes.md` — the poller tier: `PollerRunner.run(adapter)` as a
  container entry point at one replica, noting that the chart does not template it yet.
- `ak-py/src/agentkernel/integration/{slack,whatsapp,messenger,instagram,telegram,teams,gmail}/README.md`
  and `examples/api/*/README.md` — same mounting change.
- `AGENTS.md:37` — the `integration/` line gains `adapter/`.
- `.agents/skills/ak-dev-testing-conventions/SKILL.md:70` — the `test_slack_integration.py` row
  ("Slack handler on the ChatService core … pattern for integration handler tests") describes a
  pattern that no longer exists; it becomes the adapter-contract pattern.
- **Deliberately not updated** (verified): `docs/versioned_docs/**` (frozen release snapshots) and
  `docs/blog/2025-11-21-messaging-platform-integrations.md` (a dated post describing the shipped
  state at the time).
