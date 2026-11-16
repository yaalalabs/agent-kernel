# #870: Move ECS onto the shared queue pipeline — Implementation Plan

Each iteration leaves the branch green (`cd ak-py && uv run pytest tests/ -q`). Section numbers refer to
[spec.md](spec.md). Rebase the branch onto `develop` first: it is behind the commits the spec cites.

## Iteration 1: SQS reader keeps the dedup ID

- **Goal:** replies from a pipeline runner on a FIFO SQS queue carry `MessageDeduplicationId`.
- **Files:** `pipeline/transport/sqs.py`, `tests/test_pipeline_sqs_transport.py`
- **Steps:**
  1. Map `MessageDeduplicationId` in `_to_envelope` (§1).
  2. Add the dedup regression tests (Testing → `test_pipeline_sqs_transport.py`).
- **Verify:** `uv run pytest tests/test_pipeline_sqs_transport.py tests/test_pipeline_agent_runner.py -q`

## Iteration 2: Pluggable WebSocket delivery in the pipeline

- **Goal:** `IOHandler` can deliver WebSocket replies through API Gateway instead of pod push, and pod-push
  behaviour is unchanged.
- **Files:** `pipeline/io_handler.py`, `pipeline/response_handler.py`, `deployment/aws/core/websocket_service.py`,
  and their three test files
- **Steps:**
  1. Pass `endpoint_url` in `_broadcast` / `_broadcast_error` (§3).
  2. Add the `endpoint_url` guard on `AWSWebSocketHandler.broadcast` (§4).
  3. Add `IOHandler.run(ws_handler=)` and `_validate_topology(pod_push=)` (§2).
  4. Add the tests for each (Testing → response handler, IO handler, broadcast).
- **Verify:** `uv run pytest tests/test_pipeline_io_handler.py tests/test_pipeline_response_handler.py tests/test_websocket_service_broadcast.py -q`

## Iteration 3: `AWSWebsocketAPI.run` hands off to `IOHandler`

- **Goal:** ECS WebSocket mode with a queue runs on `IOHandler` + `ResponseHandler`, and direct mode is unchanged.
- **Files:** `deployment/aws/containerized/core/api/websocket_api.py`, `tests/test_ecs_io_handler.py` (rewritten)
- **Steps:**
  1. Add the queue hand-off in `AWSWebsocketAPI.run` (§5).
  2. Rewrite `test_ecs_io_handler.py` as the hand-off test.
- **Verify:** `uv run pytest tests/test_ecs_io_handler.py tests/test_ecs_websocket_routes.py tests/test_deployment_identity.py -q`

## Iteration 4: Delete the ECS-only classes and switch their callers

The deletion and the example switch land together, so no example ever imports a deleted name.

- **Goal:** `akagentrunner.py`, `akoutputconsumer.py`, `ecs_io_handler.py` and `core/api/rest_api.py` are gone,
  with no aliases, and every ECS example runs on the shared classes.
- **Files:**
  - The four modules, the three `__init__.py` files, the comment-only references (§6), and the tests that
    break.
  - Runner scripts → `AgentRunner.run`:
    - `examples/aws-containerized/{openai-dynamodb-scalable,openai-schedule,openai-stream-queue-mode,openai-websocket-scalable}/app_agent_runner.py`
    - `examples/api/livekit-voice/{openai,google}/sqs/app_agent_runner.py`
  - IO scripts:
    - `openai-dynamodb-scalable/app_rest_service.py` and `openai-schedule/app_rest_service.py` → `IOHandler.run`
    - `openai-websocket-scalable/app_rest_service.py` and `openai-stream-queue-mode/app_rest_service.py` →
      `AWSWebsocketAPI.run`
  - Comments in `openai-{stream-queue-mode,websocket-scalable}/deploy/main.tf:21`
- **Steps:**
  1. Delete the modules and update the exports (§6).
  2. Reword the comment-only references (§6 list).
  3. Delete the five ECS test files (Testing → Deleted tests).
  4. Edit `test_deployment_identity.py`, `test_ecs_sqs_consumer_parallel.py` and `test_api_http.py`.
  5. Swap the example imports and calls, and fix the comments that name `ECSIOHandler`.
  6. Check that nothing still names the deleted classes:
     `git grep -nE "ECS(AgentRunner|StreamAgentRunner|RealtimeAgentRunner|OutputConsumer|IOHandler|QueueRequestHandler)|AWSRestAPI" -- ak-py examples`
     must return only README hits (those are fixed in Iteration 7).
- **Verify:**
  - Full suite: `uv run pytest tests/ -q`
  - `make lint-check-all`
  - `./build.sh local` in `openai-dynamodb-scalable` and `openai-websocket-scalable`. These need the local
    wheel: the WebSocket hand-off is not in `agentkernel` 0.10.1.

## Iteration 5: Terraform SSE refusal

- **Goal:** `terraform plan` rejects `queue_mode + rest_sync + delta` on ECS.
- **Files:** `ak-deployment/ak-aws/containerized/variables.tf`
- **Steps:**
  1. Add the `validation` block (§7).
- **Verify:** `terraform -chdir=ak-deployment/ak-aws/containerized validate`, plus the failing `plan` described in
  spec Testing → Terraform. Record the output in the PR.

## Iteration 6: Tests

- **Goal:** the design's acceptance coverage is in place.
- **Files:** new `tests/test_ecs_shared_pipeline.py`
- **Steps:** add the rolling-deploy test (both directions, WS delta) and the Mount test (spec Testing →
  `test_ecs_shared_pipeline.py`).
- **Verify:** `uv run pytest tests/ -q` and `make lint-check-all`

## Iteration 7: Sync docs and skills

Each surface below names a deleted class (verified on `develop` @ `b982c7b8`). Update them, then confirm with
the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` flows before merge.

- **Example READMEs:**
  - `examples/aws-containerized/{openai-schedule,openai-stream-queue-mode,openai-websocket-scalable}/README.md`
  - `examples/api/livekit-voice/{openai,google}/sqs/README.md`
- **Deployment README:** `ak-deployment/ak-aws/containerized/README.md:499-500`
- **Docs site:**
  - `docs/docs/deployment/aws-containerized.md` (19 refs)
  - `docs/docs/advanced/queue-mode-guide.md` (31)
  - `docs/docs/deployment/aws-queue-mode-scalability.md` (8)
  - `docs/docs/deployment/overview.md` (4)
  - `docs/docs/agent-skills.md` (2)
  - `docs/docs/api/a2a-server.md:55`, `docs/docs/api/mcp-server.md:47`
  - Leave `versioned_docs/` untouched.
- **Dev skills:**
  - `.agents/skills/ak-dev-architecture/SKILL.md` (33 refs: the ECS class tables)
  - `.agents/skills/ak-dev-testing-conventions/SKILL.md` (1)
- **Bundled skills:**
  - `ak-py/src/agentkernel/skills/ak-cloud-deploy/SKILL.md` (17)
  - `ak-py/src/agentkernel/skills/ak-cloud-deploy/evals/evals.json` (2)
  - `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md` (2)
- **Specs:** `docs/specs/remove-direct-mode/research/blockers.md`. Close B2, and correct B5 to "ECS streams over
  WebSocket only". Older specs under `docs/specs/` stay as historical records.
- **Release notes:** a `feat!:` migration table:
  - `ECSAgentRunner.run` → `AgentRunner.run`
  - `ECSIOHandler.run` → `IOHandler.run` (REST modes) or `AWSWebsocketAPI.run` (WebSocket mode)
  - `AWSRestAPI` / `ECSOutputConsumer` → removed, no replacement needed
- **Verify:**
  `git grep -nE "ECS(AgentRunner|StreamAgentRunner|RealtimeAgentRunner|OutputConsumer|IOHandler|QueueRequestHandler)|AWSRestAPI" -- ':!docs/versioned_docs' ':!docs/specs'`
  returns only the release notes.
