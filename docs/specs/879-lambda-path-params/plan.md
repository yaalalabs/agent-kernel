# #879 (phase 1): Path-parameter routing in the Lambda REST router — Implementation Plan

## Iteration 1: Router

- **Goal:** template routes dispatch; every existing route behaves as before.
- **Files:** `ak-py/src/agentkernel/deployment/aws/serverless/core/router/rest_lambda.py`,
  `ak-py/src/agentkernel/deployment/aws/serverless/aklambda.py`
- **Steps:**
  1. Add `_resolve_route_path` and call it from `dispatch()` (spec: `_resolve_route_path`, `dispatch`).
  2. Update the `RESTLambdaRouter` and `Lambda.register` docstrings (spec: Docstrings).
- **Verify:** existing `tests/test_lambda_router.py` passes untouched.

## Iteration 2: Tests

- **Goal:** the new resolution rules are pinned.
- **Files:** `ak-py/tests/test_lambda_router.py`
- **Steps:** add `**extra` to `make_event_with_env_vars`; add the six tests listed in spec: Testing.
- **Verify:** `cd ak-py && uv run pytest tests/test_lambda_router.py tests/test_authorizer_webhook_bypass.py`

## Iteration 3: Schedule example

- **Goal:** the serverless schedule example uses `/schedules/{task_id}`, matching containerized.
- **Files:** `examples/aws-serverless/schedule-openai/{lambda_request_handler.py,lambda_test.py,README.md,deploy/main.tf}`
- **Steps:** apply the spec's example table.
- **Verify:** black and `terraform fmt -check` clean; GET / PUT / DELETE through `Lambda.handler` with a
  stubbed `ScheduleManager` reach the right handler; the weekly integration run covers the deployed path.

## Iteration 4: Sync docs and skills

- **Goal:** docs and skills describe path parameters and the new example routes.
- **Files:**
  - `docs/docs/deployment/aws-serverless.md`: "Path and query parameters" section; webhook note no
    longer says "matches the rest exactly"; Scheduling → "Management routes".
  - `docs/docs/advanced/scheduling.md`: Lambda note under Enabling; serverless example entry.
  - `ak-py/src/agentkernel/skills/ak-cloud-deploy/SKILL.md`: serverless schedule routes.
- **No update needed (verified):** `.agents/skills/ak-dev-architecture` (no description of Lambda
  route matching); `examples/aws-containerized/openai-schedule` (already `/schedules/{task_id}`);
  `docs/specs/*` and `docs/versioned_docs/*` (historical).
- **Verify:** `grep -rn "schedules/get\|schedules/amend\|schedules/cancel" docs ak-py/src examples`
  returns nothing outside `docs/specs/` and `versioned_docs/`; confirm with
  `ak-dev-sync-docs-from-branch` / `ak-dev-sync-skills-from-branch` before merge.

---

# #879 (phase 2): Conversation threads as a Lambda integration — Implementation Plan

Paths are relative to `ak-py/src/agentkernel/` unless they start with `ak-py/`, `ak-deployment/`,
`examples/`, `docs/` or `.agents/`.

## Iteration 1: Shared reply recording

- **Goal:** one reply-recording method, used by the pipeline runners; pipeline behaviour unchanged.
- **Files:** `integration/thread/recorder.py`, `pipeline/agent_runner.py`
- **Steps:**
  1. Add `ThreadRecorder.record_queued_reply` with the body of `AgentRunner._record_thread_reply`
     (spec: Reply recording).
  2. Reduce `AgentRunner._record_thread_reply` to the marker check, lazy import and delegate; pass
     the response from both call sites; delete the extraction lines in `_process_run`.
- **Verify:** `uv run pytest tests/test_thread_pipeline_recording.py tests/test_pipeline_agent_runner.py`
  passes untouched.

## Iteration 2: Thread handler seams

- **Goal:** the pipeline thread handlers expose what a Lambda host needs; their routes behave as before.
- **Files:** `integration/thread/thread_chat.py`, `api/handler.py`
- **Steps:**
  1. `ThreadRequestHandler`: `read_handler`, `_validate_chat`, `_queue_attributes`,
     `prepare_for_queue`; `run_chat` / `_enqueue_request` use them (spec: `ThreadRequestHandler`).
  2. `ThreadRESTRequestHandler`: lift the two closures into `list_threads` / `get_thread`.
  3. `AuthorisedRESTRequestHandler.authoriser` property.
- **Verify:** `uv run pytest tests/test_thread_router.py tests/test_thread_integration.py tests/test_thread_pipeline_recording.py`
  passes untouched.

## Iteration 3: Router hook

- **Goal:** the Lambda chat route can carry a hook; without one nothing changes.
- **Files:** `deployment/aws/serverless/core/router/rest_lambda.py`, `deployment/aws/serverless/aklambda.py`
- **Steps:** `ChatEnqueueHook`, `LambdaChatRejection`, `set_enqueue_hook` /
  `set_chat_enqueue_hook` on the three classes, the `_send_to_queue` call and the `_handle_request`
  branch (spec: Chat route takeover).
- **Verify:** `uv run pytest tests/test_lambda_router.py tests/test_serverless_request_handle.py tests/test_serverless_status_propagation.py`.

## Iteration 4: Lambda host package and base

- **Goal:** the Lambda hosts have their own `integration/` package, and `LambdaWebhookHost` and its
  guard sit on shared bases, unchanged in behaviour.
- **Files:** `deployment/aws/serverless/core/integration/` (new: `__init__.py`, `base.py`,
  `event_translator.py`, `webhook.py`), `deployment/aws/__init__.py`; import paths in
  `test_lambda_webhook_host.py`, `test_lambda_webhook_parity.py`, `test_lambda_event_translator.py`,
  `test_serverless_integration_delivery.py`, `test_aws_lazy_exports.py`
- **Steps:**
  1. Create the package with its docstring-only `__init__.py`; move `event_translator.py` and
     `webhook_host.py` (as `webhook.py`) from `serverless/core/` into it, no shims; repoint the
     lazy export and the tests' import paths (spec: The `integration/` package).
  2. Move `_loop`, `_run`, `_respond` into `LambdaHost` and the mode / transport / base-path checks
     into `LambdaHostGuard` in `base.py`, with `HOST_NAME` / `SUBJECT` messages (spec: `LambdaHost`).
- **Verify:** `uv run pytest tests/test_lambda_webhook_host.py tests/test_lambda_webhook_parity.py tests/test_lambda_event_translator.py tests/test_serverless_integration_delivery.py tests/test_aws_lazy_exports.py`
  passes with only the import paths changed.

## Iteration 5: `LambdaThreadHost` and reply recording on Lambda

- **Goal:** threads work end to end on Lambda: chat records and marks, the runner records the
  reply, the read routes answer.
- **Files:** `deployment/aws/serverless/core/integration/thread.py` (new), `deployment/aws/__init__.py`,
  `deployment/aws/serverless/akagentrunner.py`
- **Steps:**
  1. `LambdaThreadGuard` and `LambdaThreadHost` (spec: `LambdaThreadHost`).
  2. Lazy export plus the `TYPE_CHECKING` mirror (spec: Exports).
  3. `ServerlessAgentRunner._record_thread_reply`, called after `_send_to_output_queue`.
- **Verify:** a local script drives `Lambda.handler` with a chat event (SQS send patched), feeds the
  captured message to `ServerlessAgentRunner.handle` (output send patched), then calls both read
  routes and gets the two messages back.

## Iteration 6: Terraform

- **Goal:** the request-handler Lambda can write the thread table in queue mode.
- **Files:** `ak-deployment/ak-aws/serverless/state.tf`
- **Steps:** drop the three `queue_mode` ternaries and reword the two comments (spec: Terraform).
- **Verify:** `terraform fmt -check` and `terraform validate` in `ak-deployment/ak-aws/serverless`;
  `terraform plan` on an existing queue-mode stack shows only the request-handler IAM policy and env
  var changes.

## Iteration 7: Example

- **Goal:** a deployable `thread-openai` example.
- **Files:** `examples/aws-serverless/thread-openai/**` (spec: Example table),
  `.github/integration-test-config.yaml` (an `aws-serverless` entry after `schedule-openai`, `:83`)
- **Steps:** copy `slack-openai`, strip Slack, add `agents.py`, the request handler, `lambda_auth.py`,
  the config, the gateway endpoints and the test.
- **Verify:** black and `terraform fmt -check` clean; `lambda_test.py` against a deployed stack.

## Iteration 8: Tests

- **Goal:** every spec requirement is pinned.
- **Files:** `ak-py/tests/test_lambda_thread_host.py` (new),
  `ak-py/tests/test_serverless_agent_runner_thread.py` (new), `ak-py/tests/test_lambda_router.py`,
  `ak-py/tests/test_aws_lazy_exports.py`
- **Steps:** the cases in spec: Testing.
- **Verify:** the spec's pytest command, then the full `uv run pytest` suite.

## Iteration 9: Sync docs and skills

- **Goal:** docs and skills describe threads on Lambda.
- **Files:**
  - `docs/docs/advanced/threads.md`: a "Threads on AWS Lambda" section (host, read routes, gateway
    endpoints, authorizer scoping, `user_id`, both Lambdas need the `thread` block, the request
    handler loads the agents); the deployment table near `:274` notes the queue-mode request handler
    now gets the table.
  - `docs/docs/deployment/aws-serverless.md`: a "Conversation threads" section beside
    "Messaging integrations" (`:1347`), linking "Path and query parameters" (`:248`).
  - `docs/docs/architecture/execution-flow.md:348`: "Conversation-thread recording does not apply in
    queue mode" is now wrong; threads work in queue mode (`ThreadRequestHandler` on the pipeline,
    `LambdaThreadHost` on Lambda), and only there on Lambda.
  - `docs/docs/advanced/queue-mode-guide.md:69`: the thread note names `ThreadRequestHandler` only;
    add `LambdaThreadHost` for AWS serverless.
  - `ak-py/src/agentkernel/skills/ak-cloud-deploy/SKILL.md`: serverless threads.
  - `.agents/skills/ak-dev-architecture/SKILL.md`: `LambdaThreadHost` beside `LambdaWebhookHost`
    (Messaging Integrations, Hosting), both under `serverless/core/integration/`;
    `ThreadRecorder.record_queued_reply` in the Conversation Threads section and in the pipeline table's `agent_runner.py` row; `ServerlessAgentRunner` row
    records replies; `:701` "unlike the thread wiring which is nulled in queue mode" is now wrong.
- **No update needed (verified):** `docs/specs/*` and `docs/versioned_docs/*` (historical);
  `ak-deployment/ak-aws/serverless` README (no thread wiring note).
- **Verify:** `grep -rn "nulled in queue mode\|does not apply in queue mode" .agents docs/docs ak-py/src` returns nothing, nor does
  a grep for the hosts' old `serverless/core/` module paths; confirm
  with `ak-dev-sync-docs-from-branch` / `ak-dev-sync-skills-from-branch` before merge.
