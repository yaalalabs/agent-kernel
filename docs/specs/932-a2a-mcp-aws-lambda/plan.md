# #932: A2A and MCP on AWS Lambda through the queue pipeline — Implementation Plan

Order of work for `spec.md`. The branch is based on `develop`, not on #935 (spec: Deviation 8). Each iteration leaves the branch working and testable. Commands run from `ak-py/`.

The two breaks: Iterations 3–4 fix break 2 (inside the Lambda: the router knows only chat); Iteration 5 fixes break 1 (the
gateway door: no `/a2a` or `/mcp` route).

## Iteration 1: Spike (no production code)

- **Goal:** the three unverified assumptions are proven or the spec is amended.
- **Files:** a throwaway script outside the repo (scratchpad); results written into `spec.md` (marks change from unverified to spiked).
- **Steps:**
  1. S1, deployed: a `{proxy+}` resource plus a `/mcp` method serve `/mcp`, `/mcp/` and `/a2a/<agent>/tasks/<id>:cancel` (spec: Terraform).
  2. S2, local: the `/mcp` to `/mcp/` redirect `Location` when the path prefix is stripped; fall back to `root_path` if it is wrong (spec: `LambdaProtocolHost`).
  3. S3, deployed or documented: the MCP OAuth metadata URL on a default `execute-api` URL (spec: Deviation 6).
- **Verify:** the written results; no repo change besides `spec.md`.

## Iteration 2: Prove the workers need no change

- **Goal:** confirm the unchanged Lambda workers serve A2A and MCP in REST modes (spec: Deviation 3).
- **Files:** new `tests/test_lambda_protocol_roundtrip.py` only; no production code.
- **Steps:** the round trip from spec: Testing, in `rest_sync` and `rest_async`.
- **Verify:** `uv run pytest tests/test_lambda_protocol_roundtrip.py`. If it fails, stop and amend the spec before going on.

## Iteration 3: Translator and app plumbing

- **Goal:** a whole ASGI app can be driven from an API Gateway event on a long-lived loop.
- **Files:** `core/event_translator.py` (`develop`'s path), new `core/protocol_host.py` (`AppLifespan`),
  new `core/protocol_paths.py`.
- **Steps:**
  1. Factor scope building out of `to_request`; add `call_app` and `proxy_response_from_parts` (spec: `LambdaEventTranslator`).
  2. `AppLifespan` (spec: `AppLifespan`).
  3. `ProtocolPaths`.
- **Verify:** `uv run pytest tests/test_lambda_event_translator.py` (existing cases unchanged) plus the new translator cases.

## Iteration 4: Router lookup, host and guard

- **Goal:** an `/a2a` or `/mcp` event on the request Lambda is answered.
- **Files:** `core/protocol_host.py` (`LambdaProtocolHost`, `LambdaProtocolGuard`), `core/protocol_paths.py` (`ROUTES`),
  `core/router/rest_lambda.py` and `tests/test_lambda_router.py` (only the router change cherry-picked from `4a8af37e3`),
  `deployment/aws/__init__.py` (lazy exports). `serverless/aklambda.py` is not changed (spec: Deviation 10).
- **Steps:**
  1. Cherry-pick only the `rest_lambda.py` change and its `test_lambda_router.py` cases from `4a8af37e3` (spec: Deviation 8).
     Then the router test: a `{proxy+}` event dispatches to a route registered with `Lambda.register` (spec: Deviation 10).
     If it fails, stop and tell the reviewer before building on it.
  2. `ProtocolPaths.ROUTES`.
  3. `LambdaProtocolGuard` with its seven checks (spec: Guard).
  4. `LambdaProtocolHost` (spec: `LambdaProtocolHost`) and its lazy export.
- **Verify:** `uv run pytest tests/test_lambda_protocol_host.py tests/test_lambda_protocol_guard.py tests/test_lambda_router.py tests/test_aws_lazy_exports.py`

## Iteration 5: The gateway door (Terraform)

- **Goal:** the gateway routes `/a2a` and `/mcp` to the request Lambda when the flags are on, with no authorizer on them (the app
  authenticates, as on ECS).
- **Files:** `ak-deployment/ak-aws/serverless/variables.tf`, `state.tf`, `modules/api-gateway/{main,variables}.tf`, both READMEs.
- **Steps:**
  1. Flags `enable_a2a_server` / `enable_mcp_server` and validation; pass `proxy_routes` to the module (spec: Terraform, Deviation 11).
  2. Module resources, methods, integrations, deployment triggers; the resource templates match `ProtocolPaths.ROUTES`.
  3. Confirm the request role's response-store permissions cover delete-on-read.
- **Verify:** `terraform validate`; plan with both flags off shows no changes; plan with both on shows only the new resources.

## Iteration 6: Example and CI entry

- **Goal:** a deployable queue-mode `rest_sync` example serving A2A and MCP.
- **Files:** new `examples/aws-serverless/a2a-mcp-openai/` (request handler, agent runner, response handler, authorizer for the chat route,
  `config.yaml`, `deploy/`, test), `.github/integration-test-config.yaml`.
- **Steps:** model on `examples/aws-serverless/slack-openai`; set request-Lambda memory
  above 128 MB, `a2a.url` / `mcp.url`, `mcp.stateless_http: true`, an `identity` block; the test sends the calls in spec: Testing.
- **Verify:** `build.sh` and `terraform validate` in the example; weekly workflow dispatch for the new entry.

## Iteration 7: Tests

- **Goal:** everything in `spec.md` Testing exists and passes.
- **Files:** the new and changed test files listed in spec: Testing.
- **Steps:** finish any case not written alongside Iterations 3-4; add the pins for Deviations 2 and 4.
- **Verify:** `uv run pytest tests/test_lambda_protocol_host.py tests/test_lambda_protocol_guard.py tests/test_protocol_route_matcher.py tests/test_lambda_protocol_roundtrip.py`, then `uv run pytest`, then `make lint-check-all`.

## Iteration 8: Sync docs and skills

- **Goal:** docs and skills match the change.
- **Steps (name file and line; run `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` before merge):**
  1. `docs/docs/api/a2a-server.md:56` and `docs/docs/api/mcp-server.md:48`: add the Lambda row; state the 29 s limit, stateless MCP, and the `tasks/{id}` limit.
  2. `docs/docs/deployment/aws-serverless.md`: the host, the Terraform flags, the authentication (no authorizer, the `identity` block), the OAuth-metadata limit.
  3. `.agents/skills/ak-dev-architecture/SKILL.md` and `.claude/skills/ak-dev-architecture/SKILL.md` (`LambdaWebhookHost` text near `:626`, `:899`): add `LambdaProtocolHost`.
  4. `ak-py/src/agentkernel/skills/ak-cloud-deploy/SKILL.md`: the new flags and host.
  5. `.agents/skills/ak-dev-testing-conventions/SKILL.md` (and `.claude` copy): the new test files.
  6. Confirm no change is needed in `docs/docs/integrations/overview.md` and `messenger.md` (they mention the webhook host only).
