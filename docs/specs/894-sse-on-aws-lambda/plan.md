# #894: SSE (`rest_sync` + `delta`) on AWS Lambda — Implementation Plan

> [!TIP]
> **TL;DR:** 8 iterations. The spike comes first because it can still change the design. Each later
> iteration leaves the branch green. The `spec.md` sections are cited as §N.

| # | Iteration | Output | Depends on |
|---|---|---|---|
| 0 | Spike | Facts for §4, §8 | — |
| 1 | Shared pieces | `check_deployment`, `LambdaPaths` | — |
| 2 | Queue workers | Two Lambda fixes | — |
| 3 | Lambda host | Guard, server, middleware, exports | 1 |
| 4 | Terraform | Modules + validations | 0 |
| 5 | Example + CI | `sse-openai`, weekly entry | 3, 4 |
| 6 | Tests | Full suite + lint | 1–5 |
| 7 | Docs, skills, changelog | User-facing text | 1–5 |

## Iteration 0: Spike

- **Goal:** prove the four facts in `research/aws-response-streaming.md`, "Spike", before code depends on them.
- **Files:** none in the repo (a throwaway stack). Results go back into the research note.
- **Steps:**
  1. A FastAPI app that writes one SSE frame per second for 40 s, zipped with the LWA layer and `run.sh`.
  2. A Regional REST API, one `AWS_PROXY` integration with `response_transfer_mode = "STREAM"`, the
     streaming URI, `authorization = "NONE"`.
  3. Run `curl -N` and record the timing, the `Authorization` header the app sees, and `scope["path"]`.
  4. Confirm `lambda:InvokeFunction` is enough for the streaming invocation (§8d).
  5. Leave `timeout_milliseconds` unset and confirm a 40 s run completes (§8d).
- **Verify:** all four facts are marked **verified** in the research note.
- **Gate:** this is a hard stop. If fact 1 fails (frames arrive in one block), stop and reopen `design.md`;
  no later iteration starts. If another fact fails, update `design.md` before iteration 3. Either way, tell
  Malitha (PR #1005).

## Iteration 1: Shared pieces

- **Goal:** the shared checks and the chat-path rule exist, with no behaviour change.
- **Files:** `pipeline/io_handler.py`, `deployment/aws/serverless/core/paths.py` (new),
  `core/router/common.py`, `core/webhook_host.py`.
- **Steps:**
  1. Add `IOHandler.check_deployment`, and make `run` call it (§1). Match PR #989 exactly. If #989 merges
     first, rebase onto it and drop this step; if this PR merges first, pulindu-yl drops it from #989.
  2. Add `LambdaPaths` (§2).
  3. Make `BaseLambdaRouter._get_base_paths_from_env` and `LambdaWebhookGuard._check_base_path_env`
     delegate to it (§2).
- **Verify:** `uv run pytest tests/test_pipeline_io_handler.py tests/test_lambda_router.py tests/test_lambda_webhook_host.py`
  passes unchanged, plus the new `check_deployment` cases.

## Iteration 2: Queue workers

- **Goal:** SSE chunks travel runner → output queue → response store on Lambda.
- **Files:** `serverless/akagentrunner.py`, `serverless/akresponsehandler.py`.
- **Steps:**
  1. `ServerlessStreamAgentRunner._get_record_attributes`: `endpoint_url` only in WebSocket mode (§5a).
  2. Serverless `ResponseHandler`: `_store_chunk` and the `is_sse` branch in `process_message` and
     `on_permanent_failure` (§5b).
- **Verify:** `uv run pytest tests/test_akagentrunner_stream.py tests/test_akresponsehandler.py tests/test_serverless_integration_delivery.py`
  with the new cases from spec "Testing".

## Iteration 3: Lambda host

- **Goal:** `LambdaStreamServer.run()` serves SSE from the shared app.
- **Files:** `serverless/core/stream_server.py` (new), `deployment/aws/__init__.py`,
  `core/router/rest_lambda.py`.
- **Steps:**
  1. `LambdaStreamGuard` (§3).
  2. `LambdaChatPathMiddleware` and `LambdaStreamServer`, including the logged guard failure in `run` (§4).
  3. The lazy export (§7).
  4. The new refusal text (§6).
- **Verify:** `uv run pytest tests/test_lambda_stream_server.py tests/test_aws_lazy_exports.py tests/test_lambda_router.py`.

## Iteration 4: Terraform

- **Goal:** SSE mode deploys with `STREAM` integrations, and every other stack plans no change.
- **Files:** `ak-aws/serverless/state.tf`, `variables.tf`, `modules/request-handler/{main,variables}.tf`,
  `modules/api-gateway/{main,variables}.tf`.
- **Steps:**
  1. `local.is_sse_mode` and the module wiring (§8a).
  2. The four `message_type` validations (queue mode, FIFO, store, authorizer) and the description fix (§8b).
  3. `response_streaming` on the request-handler module (§8c).
  4. `response_streaming` and `lambda_function_arn` on the api-gateway module (§8d).
- **Verify:**
  - `terraform validate` passes.
  - `terraform plan` of `examples/aws-serverless/scalable-openai` shows **no changes**. This checks the
    `null` transfer mode.
  - Each validation fails a plan with its message.

## Iteration 5: Example and CI

- **Goal:** a deployable example streams end to end and runs weekly.
- **Files:** `examples/aws-serverless/sse-openai/**` (new), `.github/integration-test-config.yaml`.
- **Steps:**
  1. Build the example from `scalable-openai` (§9), with the layer ARN pinned from the spike.
  2. `build.sh local` force-reinstalls the branch wheel with `--no-cache-dir` (testing skill, CI section).
  3. Add the security-group inputs and the weekly entry.
- **Verify:** `./deploy/deploy.sh local`, then `uv run --no-sync pytest lambda_test.py` shows frames
  arriving before the run ends. `make lint-check-all` passes.

## Iteration 6: Tests

- **Goal:** everything in spec "Testing" is present and green.
- **Files:** `tests/test_lambda_stream_server.py` (new); the extended files in spec "Testing".
- **Steps:**
  1. Fill any case iterations 1–3 deferred.
  2. Run the full suite and lint.
- **Patch targets that move:** none (spec "Testing").
- **Verify:** `cd ak-py && uv run pytest` and `make lint-check-all`.

## Iteration 7: Sync docs, skills and changelog

- **Goal:** no surface still says SSE is impossible on Lambda.
- **Docs:**

  | File | Line | Change |
  |---|---|---|
  | `docs/docs/deployment/aws-serverless.md` | `:19` (mode table) | Add the `rest_sync` + `delta` row |
  | `docs/docs/deployment/aws-serverless.md` | `:23-24` ("No SSE on Lambda" box) | Replace with the `LambdaStreamServer` setup, auth and the `authorizer` → `identity` migration (design §5), which routes reach the app (design §3), limits incl. concurrency and retry repeats (design §7) |
  | `docs/docs/deployment/aws-serverless.md` | `:1023` | `delta` works with `rest_sync` (SSE, `LambdaStreamServer`) and `async` |
  | `docs/docs/architecture/execution-flow.md` | `:207`, `:429` | SSE row's target column includes AWS Lambda |

- **Skills:**

  | File | Line | Change |
  |---|---|---|
  | `ak-py/src/agentkernel/skills/ak-cloud-deploy/SKILL.md` | `:849` | Lambda SSE through `LambdaStreamServer` |
  | `.agents/skills/ak-dev-architecture/SKILL.md` | `:2059` | The streaming flow's Lambda line; a `LambdaStreamServer` entry beside `LambdaWebhookHost` |
  | `.agents/skills/ak-dev-testing-conventions/SKILL.md` | `test_lambda_router.py` row | Mention the new refusal text; add a `test_lambda_stream_server.py` row |

- **Changelog:** `changelog.d/894.added.md`: "SSE streaming (`execution.mode: rest_sync` with
  `message_type: delta`) on the AWS Lambda serverless deployment, through `LambdaStreamServer` and the
  Lambda Web Adapter." This covers spec behavioural changes 1–5. No `breaking` entry: no working
  deployment changes.
- **Verify:** run the `ak-dev-sync-docs-from-branch`, `ak-dev-sync-skills-from-branch` and
  `ak-dev-sync-changelog-from-branch` flows, and fix what they report.
