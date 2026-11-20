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
