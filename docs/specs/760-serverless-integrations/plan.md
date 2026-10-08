# #760: Messaging integrations on AWS Lambda: deliver replies and receive webhooks — Implementation Plan

This plan builds [`spec.md`](spec.md) in twelve iterations: part 1 (1-3), part 2 (4-8), then
Terraform, the example, tests, and the docs sync. Each iteration leaves the branch green.

- "§N" refers to a numbered section of spec.md, and "Testing: X" to a subsection of its Testing
  section.
- Commands run from `ak-py/` unless they say otherwise.
- A test file listed under **Files** gets only the tests for that iteration's component.
- Suites marked **unmodified** must pass with no edit to the test file.

## Iteration 1: `IntegrationDelivery`, and the pipeline on it

- **Goal:** the shared class exists and is unit-tested, and the pipeline delivers through it with no
  change in behaviour.
- **Files:**
  - `src/agentkernel/pipeline/integration_delivery.py` (new)
  - `src/agentkernel/pipeline/response_handler.py`
  - `src/agentkernel/pipeline/agent_runner.py`
  - `tests/test_pipeline_integration_delivery.py` (new)
- **Steps:**
  1. Write `IntegrationDelivery` as §1 describes: the four return-address helpers, `deliver`,
     `deliver_permanent_failure`, and the lazy `_outbound_adapter`.
  2. Write the tests from "Testing: New: `test_pipeline_integration_delivery.py`", including the
     import-hygiene check.
  3. Move `ResponseHandler` onto it (§2): build it in `__init__`, switch the two integration
     branches, delete the three private helpers, and drop the unused imports.
  4. Move `AgentRunner`/`StreamAgentRunner` onto it (§2): the forwarding rule, the two integration
     checks, and the docstring.
- **Verify:**
  - `uv run pytest tests/test_pipeline_integration_delivery.py`
  - **unmodified:** `uv run pytest tests/test_pipeline_response_handler.py tests/test_pipeline_agent_runner.py tests/test_integration_roundtrip.py tests/test_thread_pipeline_recording.py`

## Iteration 2: The serverless agent runners

- **Goal:** an integration message reaches the output queue with its return address, and its
  prebuilt `requests` reach the agent. STREAM mode hands it to the non-streaming runner.
- **Files:**
  - `src/agentkernel/deployment/aws/serverless/akagentrunner.py`
  - `tests/test_serverless_integration_delivery.py` (new): the Runner, Stream runner and Import
    hygiene groups
  - `tests/test_akagentrunner_stream.py`: the two fakes gain `requests=None`
- **Steps:**
  1. `ServerlessAgentRunner` (§3): pass `requests`, add `routing_attributes`, and send them.
  2. `ServerlessStreamAgentRunner` (§4): the integration guard in `process_message` and
     `on_permanent_failure`, and `requests` on the stream path.
  3. Update the stream-test fakes, then add the three test groups.
- **Verify:**
  - `uv run pytest tests/test_serverless_integration_delivery.py tests/test_akagentrunner_stream.py`
  - **unmodified:** `uv run pytest tests/test_serverless_agent_runner_schedule.py tests/test_serverless_status_propagation.py`

## Iteration 3: The serverless response handler

- **Goal:** integration replies are delivered to the platform in every mode, and permanent failures
  are delivered again (the `KeyError` fix).
- **Files:**
  - `src/agentkernel/deployment/aws/serverless/akresponsehandler.py`
  - `tests/test_serverless_integration_delivery.py`: the Response handler, Permanent failure and
    Missing extra groups
- **Steps:**
  1. Add `_get_integration_delivery` and `_decode_body`, and make `_construct_message_for_store`
     use `_decode_body` (§5).
  2. `process_message`: the integration branch first (§5).
  3. `on_permanent_failure`: the group id from the system attributes, the integration branch, and
     the session id set once (§5).
  4. Add the three test groups.
- **Verify:**
  - `uv run pytest tests/test_serverless_integration_delivery.py`
  - **unmodified:** `uv run pytest tests/test_akresponsehandler.py tests/test_serverless_status_propagation.py`

## Iteration 4: Packaging and the lazy `agentkernel.api`

- **Goal:** `agentkernel[aws,<platform>]` is enough for both Lambdas, and importing the webhook
  handler no longer loads `uvicorn`.
- **Files:**
  - `pyproject.toml`
  - `uv.lock`
  - `src/agentkernel/api/__init__.py`
  - `tests/test_packaging_extras.py` (new)
  - `tests/test_aws_lazy_exports.py`: the "webhook loads neither `api.http` nor `uvicorn`" test
- **Steps:**
  1. Add `fastapi` to the six webhook extras and `aiohttp` to `slack`, then run `uv lock` (§13).
  2. Turn `api/__init__.py` into lazy exports (§13).
  3. Add the static extras test and the lazy-import test.
  4. Run the clean-environment check from "Testing: Clean-environment verification" for `aws,slack`,
     `aws,whatsapp` and `aws,teams`, in a scratch venv outside the repo.
- **Verify:**
  - `uv run pytest tests/test_packaging_extras.py tests/test_aws_lazy_exports.py`
  - **unmodified:** `uv run pytest tests/test_api_http.py tests/test_pipeline_io_handler.py tests/test_thread_pipeline_recording.py tests/test_integration_webhook_handler.py`
    (these hold the `agentkernel.api.http` patch targets)
  - The clean-environment check prints success for all three extras, with `uvicorn` absent.

## Iteration 5: Built-in routes and the adapter additions

- **Goal:** the built-in webhook paths have one definition, and adapters can report missing
  verification settings. Every path stays exactly as it is.
- **Files:**
  - `src/agentkernel/integration/adapter/routes.py` (new)
  - `src/agentkernel/integration/adapter/base.py`, `webhook.py`, `__init__.py`, `testing.py`
  - `src/agentkernel/integration/{slack,teams,telegram,whatsapp,messenger,instagram}/adapter.py`
- **Steps:**
  1. `WebhookRoute` and `BUILTIN_WEBHOOK_ROUTES` (§6), then point the six adapters' path attributes
     at the table.
  2. `InboundAdapter.missing_verification_settings`, and the WhatsApp, Messenger, Instagram and
     Telegram overrides (§7).
  3. The `WebhookRESTRequestHandler.adapter` property, and the `WebhookRoute` lazy export (§7).
     `WebhookRouteMatcher`'s export arrives in iteration 8, with its module.
  4. The contract test `test_a_builtin_is_served_where_the_authorizer_expects` (§6).
- **Verify:**
  - `uv run pytest tests/test_integration_adapter_contract.py`, which runs the new contract test for
    every built-in
  - **unmodified:** `uv run pytest tests/test_integration_webhook_handler.py tests/test_integration_roundtrip.py tests/test_slack_integration.py tests/test_teams_integration.py tests/test_telegram_integration.py tests/test_whatsapp_integration.py tests/test_messenger_integration.py tests/test_instagram_integration.py tests/test_integration_poller_runner.py`
  - The overrides are exercised by iteration 7's guard tests.

## Iteration 6: `LambdaEventTranslator`

- **Goal:** an API Gateway v1 proxy event becomes a real Starlette `Request`, and a handler's
  result or exception becomes the proxy response FastAPI would have sent.
- **Files:**
  - `src/agentkernel/deployment/aws/serverless/core/event_translator.py` (new)
  - `tests/test_lambda_event_translator.py` (new)
- **Steps:**
  1. Write the class as §8 describes: `to_request`, `to_proxy_response`, `error_to_proxy_response`,
     and the four helpers.
  2. Do not import it from `core/__init__.py`.
  3. Write the tests from "Testing: New: `test_lambda_event_translator.py`".
- **Verify:** `uv run pytest tests/test_lambda_event_translator.py`

## Iteration 7: `LambdaWebhookHost`, `LambdaWebhookGuard` and the `agentkernel.aws` export

- **Goal:** a `LambdaWebhookHost(WebhookRESTRequestHandler(...))`, its endpoints registered with
  `Lambda.register`, serves webhooks through the existing router, and refuses to build for a
  deployment that could not work, on cold start.
- **Files:**
  - `src/agentkernel/deployment/aws/serverless/core/webhook_host.py` (new)
  - `src/agentkernel/deployment/aws/__init__.py`
  - `tests/test_lambda_webhook_host.py` (new)
  - `tests/test_aws_lazy_exports.py`: the "`Lambda` loads neither `fastapi` nor `webhook_host`" and
    "touching `LambdaWebhookHost` through `agentkernel.aws` resolves it" tests
- **Steps:**
  1. `LambdaWebhookHost` (§9): the guarded constructor, `handle`, `challenge`, `_respond`, and the
     class-level loop.
  2. `LambdaWebhookGuard` (§9): the five checks, in order.
  3. The `LambdaWebhookHost` lazy export in `deployment/aws/__init__.py` (§13). `Lambda` is
     unchanged: the application registers the host's endpoints with `Lambda.register` (§10).
  4. Write the tests from "Testing: New: `test_lambda_webhook_host.py`": registered routes, loop,
     guards, and the FastAPI-mirror replay.
- **Verify:**
  - `uv run pytest tests/test_lambda_webhook_host.py tests/test_aws_lazy_exports.py`
  - **unmodified:** `uv run pytest tests/test_lambda_router.py tests/test_ws_lambda_stream.py tests/test_serverless_request_handle.py`

## Iteration 8: The authorizer bypass

- **Goal:** with a bypass, integration routes pass the authorizer by path and method. Everything
  else is authorized exactly as before.
- **Files:**
  - `src/agentkernel/integration/adapter/route_matcher.py` (new)
  - `src/agentkernel/integration/adapter/__init__.py`: the `WebhookRouteMatcher` lazy export
  - `src/agentkernel/deployment/aws/serverless/akauthorizer.py`
  - `tests/test_authorizer_webhook_bypass.py` (new)
  - `tests/test_aws_lazy_exports.py`: the "authorizer and matcher load neither `fastapi` nor
    `slack_bolt`" test
- **Steps:**
  1. `WebhookRouteMatcher` (§11): the constructor, `for_integrations`, `__call__`, and the base-path
     derivation.
  2. `APIGatewayAuthorizer(bypass=...)` and `_bypass_policy` (§12).
  3. Write the tests from "Testing: New: `test_authorizer_webhook_bypass.py`", including the one
     that pins the matcher to the router's stripping.
- **Verify:**
  - `uv run pytest tests/test_authorizer_webhook_bypass.py tests/test_aws_lazy_exports.py`
  - **unmodified:** `uv run pytest tests/test_akauthorizer.py`

## Iteration 9: Terraform

- **Goal:** the stock stack lets a webhook reach the request handler and work there: base path on
  the authorizer, attachment table and output queue URL at the edge.
- **Files** (under `ak-deployment/ak-aws/serverless/`):
  - `state.tf`
  - `modules/request-handler/variables.tf`
  - `modules/request-handler/main.tf`
  - `README.md`
  - `modules/request-handler/README.md`
- **Steps:**
  1. The multimodal table reaches the request handler under `queue_mode` (§14 item 1).
  2. `authorizer_info` merges `API_BASE_PATH`/`API_VERSION`, with the `null` guard (§14 item 2).
  3. The request-handler module's new `output_queue_url` input and its environment variable, wired
     from `local.output_queue_url` (§14 item 3).
  4. Both READMEs (§14 item 6).
  5. Leave every module `version` pin alone.
- **Verify** (from the repo root):
  - `terraform fmt -check -recursive ak-deployment/ak-aws/serverless`
  - `terraform -chdir=ak-deployment/ak-aws/serverless init -backend=false` then
    `terraform -chdir=ak-deployment/ak-aws/serverless validate`
  - With AWS credentials at hand: `terraform plan` a queue-mode example (for example
    `examples/aws-serverless/scalable-openai/deploy`) with its module `source` temporarily pointed at
    the local stack. It must show only spec behavioural changes 10-12, as in-place updates or
    additions. Do not commit the source change.

## Iteration 10: The example

- **Goal:** `examples/aws-serverless/slack-openai/` deploys the whole path, and proves it without a
  Slack workspace.
- **Files:** `examples/aws-serverless/slack-openai/`:
  - `lambda_request_handler.py`, `lambda_agent_runner.py`, `lambda_response_handler.py`, `lambda_auth.py`
  - `config.yaml`, `pyproject.toml`, `uv.lock`, `build.sh`, `lambda_test.py`, `README.md`
  - `deploy/{main.tf,variables.tf,outputs.tf,providers.tf,terraform.tfvars,deploy.sh}`
- **Steps:**
  1. Start from `examples/aws-serverless/schedule-openai/`'s layout and per-Lambda extras, then write
     each file as §15 describes.
  2. Copy the module `version` pin the sibling examples carry. Never bump it by hand.
  3. `lambda_test.py`: the three smoke checks in "Testing: Example smoke test".
  4. Do not add the example to `.github/integration-test-config.yaml`.
- **Verify:**
  - `make lint-check-all` (repo root)
  - `terraform fmt -check -recursive examples/aws-serverless/slack-openai/deploy`
  - With the module `source` temporarily pointed at the local stack, because the pinned release lacks
    iteration 9 (not committed): `terraform init -backend=false && terraform validate` in `deploy/`.
  - Where an AWS account is available: `deploy/deploy.sh local`, then
    `AK_TEST_ENDPOINT=... uv run pytest lambda_test.py`, then destroy.

## Iteration 11: Tests

- **Goal:** the cross-cutting proofs, and a green suite.
- **Files:**
  - `tests/test_serverless_integration_delivery.py`: the Round trip and End to end tests
  - `tests/test_lambda_webhook_parity.py` (new)
- **Steps:**
  1. The round trip over a real `SQSTransport`, with only `boto3.client` patched and at most 10
     `MessageAttributes` ("Testing: Round trip").
  2. The end-to-end test: a signed Slack event goes to `Lambda.handler`, then the host's `handle`
     registered with `Lambda.register`, the input record, `ServerlessAgentRunner`, `ResponseHandler`,
     and the recording adapter. The handler builds its producer from `execution.queues` ("Testing:
     End to end").
  3. The per-adapter parity suite: Meta and Telegram deliveries from the contract subclasses, and
     Slack and Teams as HTTP-level deliveries ("Testing: New: `test_lambda_webhook_parity.py`").
  4. Run the full suite and the lint check.
- **Verify:**
  - `uv run pytest`
  - `make lint-check` (repo root)
  - `git diff develop --stat -- ak-py/tests` touches no file in "Testing: Existing tests that must
    pass unmodified". The only edited files are `test_akagentrunner_stream.py` and
    `test_aws_lazy_exports.py`.

## Iteration 12: Sync docs and skills

- **Goal:** the docs and skills describe what shipped.
- **Files:**
  - `docs/docs/deployment/aws-serverless.md`:
    - the new "Messaging integrations" section after "Scheduling (EventBridge Scheduler)" (`:1204`)
    - a link to it from "Cold Start Mitigation" (`:1257-1261`)
  - `docs/docs/advanced/queue-mode-guide.md`, "How It Works in Lambda (Serverless)" (`:375`): the
    dispatch and `LambdaWebhookHost` bullets
  - `docs/docs/integrations/overview.md` (`:77-79`): serverless hosting
  - `docs/docs/integrations/telegram.md:287`, `messenger.md:505`, `instagram.md:530`: link the new
    section
  - `.agents/skills/ak-dev-architecture/SKILL.md`:
    - the pipeline rows (`:773-774`), plus an `integration_delivery.py` row
    - coupling rule 2 (`:799`)
    - the Hosting bullet (`:546`)
    - the `ServerlessAgentRunner` row (`:1014`)
    - the `agentkernel.api` lazy exports
  - `.agents/skills/ak-dev-testing-conventions/SKILL.md`: rows for the seven new test files, and the
    `test_aws_lazy_exports.py` additions
  - `.agents/skills/ak-dev-new-messaging-integration/SKILL.md`:
    - the hosting table (`:29-36`)
    - steps 2 and 7 (the route table)
    - `missing_verification_settings`
    - the checklist (`:300`)
  - `ak-py/src/agentkernel/skills/ak-add-integration/SKILL.md`: the Lambda wiring (Step 3, `:43` onwards)
  - `ak-py/src/agentkernel/skills/ak-cloud-deploy/SKILL.md`, AWS Serverless (`:300`): webhook routes,
    the bypass, TTL 0
- **Checked and needing no update:**
  - `docs/docs/integrations/{slack,whatsapp,teams,gmail}.md`: none mentions serverless hosting.
  - `docs/docs/deployment/aws-queue-mode-scalability.md`: no integration hosting.
  - `README.md:214` and the docs-site platform inventories (`docs/src/pages/features.tsx`,
    `index.tsx`): no platform is added.
  - `ak-deployment/ak-aws/common/`: the authorizer module is untouched (§14 item 2).
- **Verify:** confirm with the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch`
  flows before merge.
