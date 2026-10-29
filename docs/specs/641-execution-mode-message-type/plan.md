# #641: Split `execution.mode` into an invocation mode and a reply `message_type` — Implementation Plan

This plan builds [`spec.md`](spec.md) in eight iterations. The new config lands first, beside
`stream`. The call sites then move onto it, layer by layer. `stream` is removed only once nothing
reads it. Deployment, examples, the full test pass and the docs sync come last. Each iteration
leaves the branch green.

- "§N" refers to a numbered section of spec.md, and "Testing: X" to its Testing section.
- Commands run from `ak-py/` unless they say otherwise.
- "Fakes" means the hand-built `execution` stubs that spec.md "Config fakes" says must become a real
  `_ExecutionConfig`. Each iteration converts the fakes its call sites reach.
- Between Iteration 2 and Iteration 4, `stream` is only half supported. Migrated call sites read the
  predicates, which treat it as neither WebSocket nor delta (so plain `rest_sync`), while the rest
  still read `STREAM`. A test keeps `stream` only while the code it exercises still reads `STREAM`,
  and no intermediate commit is deployed.

## Iteration 1: `ReplyMessageType`, `message_type` and the predicates

- **Goal:** the pair loads, validates and resolves. `stream` still loads, and nothing reads the new
  field yet.
- **Files:** `src/agentkernel/core/model.py`, `src/agentkernel/core/config.py`, `tests/test_config.py`
- **Steps:**
  1. Add `ReplyMessageType` and rewrite the `ExecutionMode` docstring (§1). Keep `STREAM` for now.
  2. Add `message_type`, `_check_message_type` and the four predicates to `_ExecutionConfig` (§2).
     Update the `mode` description.
  3. Add the matrix, default and predicate tests from Testing: `tests/test_config.py`, except the
     `stream` rejection.
- **Verify:** `uv run pytest tests/test_config.py`, then `uv run pytest`.

## Iteration 2: Pipeline, direct REST, threads and A2UI on the predicates

- **Goal:** no file under `pipeline/`, `api/`, `integration/thread/` or `a2ui/` compares a mode to
  `STREAM` or spells `(ASYNC, STREAM)`.
- **Files:**
  - `src/agentkernel/pipeline/{io_handler,agent_runner,response_handler,request_handler}.py`
  - `src/agentkernel/pipeline/ws/gateway.py`
  - `src/agentkernel/api/handler.py`, `src/agentkernel/integration/thread/thread_chat.py`, `src/agentkernel/a2ui/hook.py`
  - their tests (Testing: Existing tests that change, plus the pipeline, request-handler,
    response-handler, A2UI and direct-REST new tests)
- **Steps:**
  1. `IOHandler`: predicates, runner selection, and `_validate_topology` without `mode`, with check 4 (§3).
  2. `AgentRunner.run`, the `StreamAgentRunner` `USER_ID` rule, `ResponseHandler.process` and
     `on_permanent_failure`, and `RequestHandler.run_chat` / `_reject_unroutable` (§3).
  3. `WebSocketGateway._validate` (§3). Direct REST, threads and A2UI (§4).
  4. Move these tests' `stream` cases to the pair (`rest_sync + delta` or `async + delta`, per
     Testing), convert their fakes, and add the new tests.
- **Verify:** `uv run pytest tests/test_pipeline_*.py tests/test_thread_pipeline_recording.py tests/test_a2ui_hook.py tests/test_api_multipart_fields.py tests/test_rest_handler_poll.py tests/test_realtime_pool.py`,
  then `uv run pytest`.

## Iteration 3: AWS serverless and containerized on the predicates

- **Goal:** no file under `deployment/aws/` reads `STREAM`, and the three new startup refusals exist.
- **Files:**
  - `src/agentkernel/deployment/aws/serverless/{aklambda,akagentrunner,akresponsehandler}.py`
  - `src/agentkernel/deployment/aws/serverless/core/router/{rest_lambda,ws_lambda}.py`, `.../core/webhook_host.py`
  - `src/agentkernel/deployment/aws/containerized/{ecs_io_handler,akoutputconsumer,akagentrunner}.py`, `.../core/api/websocket_api.py`
  - their tests
- **Steps:**
  1. Serverless (§5): the WebSocket switch, runner dispatch, response-handler split, WS direct
     stream, the `get_routes` refusal, deleting `_handle_stream`, and the webhook `message_type` check.
  2. Containerized (§6): the `ECSIOHandler` refusal and branch, the output-consumer split, runner
     dispatch, and WS direct stream.
  3. Move the `STREAM` cases in `test_ws_lambda_stream.py`, `test_akresponsehandler.py`,
     `test_serverless_integration_delivery.py`, `test_ecs_websocket_routes.py`,
     `test_ecs_akoutputconsumer.py` and `test_lambda_webhook_host.py` to `async + delta`. Convert
     the fakes (including `test_serverless_status_propagation.py`, `test_ecs_io_handler.py`,
     `test_ecs_output_consumer_status.py`, `test_ecs_akagentrunner_realtime.py`). Delete
     `test_handle_stream_returns_400_not_raises`, and add the Lambda-router, ECS and webhook tests.
- **Verify:** `uv run pytest tests/test_ws_lambda_stream.py tests/test_akresponsehandler.py tests/test_serverless_*.py tests/test_lambda_*.py tests/test_ecs_*.py`,
  then `uv run pytest`.

## Iteration 4: Retire `stream`

- **Goal:** `ExecutionMode.STREAM` is gone and `mode: stream` fails at load with the migration message.
- **Files:** `src/agentkernel/core/model.py`, `src/agentkernel/core/config.py`, `tests/test_config.py`
- **Steps:**
  1. Delete `STREAM` (§1). Add `STREAM_MIGRATION_MESSAGE` and `_reject_legacy_stream` (§2).
  2. Add the YAML and env `stream` tests (Testing: `tests/test_config.py`).
  3. Confirm nothing still reads it: `grep -rnE 'ExecutionMode\.STREAM|== "stream"|mode *= *"stream"' src tests`
     returns nothing.
  4. Sweep the prose (§2 rule 5): `grep -rnw STREAM src` returns only log tags such as
     `[STREAM AGENT START]`.
- **Verify:** `uv run pytest`.

## Iteration 5: Terraform and Helm

- **Goal:** both AWS modules and the chart accept `message_type` and refuse `stream`.
- **Files:**
  - `ak-deployment/ak-aws/serverless/{variables,state}.tf`
  - `ak-deployment/ak-aws/containerized/{variables,state,rest_service,queue_mode,iam,outputs}.tf`
  - `ak-deployment/ak-aws/containerized/modules/{rest-service,agent-runner}/{variables,main}.tf`
  - `ak-deployment/ak-k8s/chart/values.yaml`, `.../templates/configmap-env.yaml`
  - `.github/workflows/chart-test.yaml`
- **Steps:**
  1. Serverless and containerized changes as listed in §7. Leave every `version` pin alone.
  2. Helm value, template and the two CI renders (§8).
- **Verify:**
  - From each module directory: `terraform fmt -check -recursive` and `terraform init -backend=false && terraform validate`.
  - `helm template smoke ak-deployment/ak-k8s/chart -f ak-deployment/ak-k8s/chart/values-baremetal.yaml --set execution.mode=async --set execution.messageType=delta --set wsGateway.enabled=true --set wsGateway.auth.token=render | grep 'AK_EXECUTION__MESSAGE_TYPE: "delta"'`.

## Iteration 6: Examples

- **Goal:** no example sets `stream`.
- **Files:** the four examples in §9 (`config.yaml`, `deploy/main.tf`, READMEs,
  `openai-stream-queue-mode/app_agent_runner.py:29`, `pydanticai-streaming/app_test.py:5`), plus the
  README-only mentions listed there.
- **Steps:**
  1. Apply the §9 table.
  2. Run the SSE example's own test against `rest_sync + delta`.
- **Verify:**
  - `cd examples/api/pydanticai-streaming && ./build.sh && uv run pytest app_test.py` (needs `OPENAI_API_KEY`).
  - `grep -rnE 'mode: *"?stream|mode=stream|execution_mode *= *"stream"|AK_EXECUTION__MODE=stream' examples` returns nothing.
  - The three AWS examples run against the new module input only after the module release bumps
    their pins. This is noted in the PR, and they are not deployed from this branch.

## Iteration 7: Tests

- **Goal:** every Testing item exists and the whole suite passes.
- **Steps:**
  1. Walk spec.md Testing line by line against the files above, and add anything an earlier
     iteration missed.
  2. Run the full suite. Any failure that comes from a fake reaching a changed call site gets that
     fake converted, not a weaker assertion.
- **Verify:** `uv run pytest` passes, `make lint-check-all` (repo root) passes, and
  `chart-test.yaml` passes in CI.

## Iteration 8: Sync docs and skills

- **Goal:** no doc or skill describes `stream` as a mode, and every one documents the pair.
- **Files:**
  - **Docs site** (`docs/docs/`): `intro.md`, `advanced/{a2ui,human-in-the-loop,queue-mode-guide,threads,traceability}.md`,
    `api/rest-api.md`, `architecture/{execution-flow,overview}.md`, `core-concepts/{overview,runner,runtime}.md`,
    `deployment/{aws-containerized,aws-queue-mode-scalability,aws-serverless,azure-containerized,gcp-containerized,gcp-serverless,local,overview}.md`,
    `examples/overview.md`, `frameworks/{google-adk,overview,pydantic-ai}.md`, `integrations/{agui,hooks}.md`.
    `docs/versioned_docs/` and `docs/specs/` stay as written.
  - **Package and deployment READMEs:** `ak-py/README.md`, `ak-deployment/ak-k8s/README.md:173-179`,
    `ak-deployment/ak-aws/serverless/README.md`, `.../serverless/modules/ws-connection-handler/README.md`,
    `ak-deployment/ak-aws/containerized/README.md`, `.../containerized/modules/README.md` (the
    `execution_mode` and new `message_type` inputs).
  - **Bundled skills:** `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md:676`,
    `ak-py/src/agentkernel/skills/ak-cloud-deploy/SKILL.md`.
  - **Dev skills:**
    - `.agents/skills/ak-dev-architecture/SKILL.md`: `:103` (`execution.mode: stream`), `:384`, the
      pipeline table rows `:873-878` (the `USER_ID` split goes away), and `:1131-1134`, `:1178` (ECS and
      serverless STREAM dispatch). Add the four `_ExecutionConfig` predicates to the AKConfig section (`:268`).
    - `.agents/skills/ak-dev-testing-conventions/SKILL.md:122` (`test_ws_lambda_stream.py` is now
      "`async + delta`"), plus a line on building real `_ExecutionConfig` fakes in "Monkeypatching Config" (`:282`).
  - **Verified as needing no update:** `.agents/skills/ak-dev-new-framework-integration/SKILL.md`. Its
    "stream" hits (`:122`, `:186`) are the runner's `stream()` method, not the mode.
- **Steps:**
  1. Update each file to the pair.
  2. Run `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` to catch anything the list missed.
  3. Write the PR description's "Breaking changes" section (the release-notes source): the two-line
     `stream` migration and the removal of `ExecutionMode.STREAM`.
- **Verify:** `grep -rnE 'mode: *stream|mode=stream|execution_mode *= *"stream"|ExecutionMode\.STREAM|`stream` mode' docs/docs ak-py/README.md ak-py/src/agentkernel/skills .agents/skills ak-deployment --include='*.md'`
  returns only intended mentions (for example, "`stream` was removed"), and `cd docs && npm run build` succeeds.
