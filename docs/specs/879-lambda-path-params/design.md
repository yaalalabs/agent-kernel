# #879 (phase 1): Path-parameter routing in the Lambda REST router

`RESTLambdaRouter` matches only the concrete request path, so a route registered with a path
parameter (`Lambda.register("/threads/{session_id}", ...)`) can never dispatch. Phase 1 makes it
dispatch by looking the route up under the resource template API Gateway already matched
(`event["resource"]`), so the router itself never matches paths. Phase 2 of #879 (the
`ThreadLambdaHandler` thread read routes) builds on this and is a separate change.

## Motivation

- `dispatch()` keys the route lookup on the concrete path only:
  - `event_path = event.get("path") or event.get("resource") or "/"`
    (`ak-py/src/agentkernel/deployment/aws/serverless/core/router/rest_lambda.py:377` on `develop`).
  - The key is `event_path.removeprefix(env_base_path)` (`rest_lambda.py:386` on `develop`), so
    `GET /api/v1/threads/abc123` looks up `/threads/abc123` and never finds `/threads/{session_id}`.
- `register()` already stores templates verbatim: `_normalize_path` only fixes the leading and
  trailing slashes (`router/common.py:22`), so `{...}` survives into `_routes` (`rest_lambda.py:351`
  on `develop`).
- API Gateway REST v1 already does the matching: the Lambda proxy event carries the matched template
  in `resource` and the values in `pathParameters`.
- The Terraform module already accepts template paths: `gateway_endpoints` paths are split on `/`
  into up to three `path_part`s (`ak-deployment/ak-aws/serverless/modules/api-gateway/main.tf:5-13`),
  the integration is `AWS_PROXY` (`:115`), and the Lambda permission covers `execution_arn/*/*` (`:124`).
- The gap already shapes code: `examples/aws-serverless/schedule-openai` used `/schedules/get`,
  `/schedules/amend` and `/schedules/cancel` with the task id in the query or body, documented as
  "no `{task_id}` path parameters".
- #527 found the gap and drafted a fix, then dropped it from scope
  (`docs/specs/527-thread-store-deployment/design.md`, Non-goals).

## Requirements

### Route resolution (`RESTLambdaRouter`)

- A route registered as `Lambda.register("/foo/{id}", method=...)` dispatches when API Gateway
  matched that template.
  - Lookup key: `event["resource"]` with the `/<api_base_path>/<api_version>` prefix stripped.
  - Handlers read the values from `event["pathParameters"]`; the router does not parse them.
- The router does no path matching of its own: when templates overlap, API Gateway's precedence
  decides (a static segment beats a `{parameter}` at the same level).
- Fallback to the concrete path when the resource template is not registered for the method.
  - Keeps a `{proxy+}` resource in front of the Lambda working (its `resource` is `/{proxy+}`).
  - Keeps events without `resource` working (ALB targets, direct invokes, hand-built test events).
- Unchanged paths:
  - The chat endpoint check (`event_path == env_agent_endpoint`) still compares the concrete path.
  - The no-env-vars branch still sends everything to the default chat handler.
  - The no-match error still names the concrete path.
  - Static routes resolve as before (`resource == path` for them).

### Configuration and Terraform

- No new configuration, no new `AKConfig` fields, no Terraform module change.
  - Deployers declare templates in `gateway_endpoints` (`{ path = "orders/{order_id}", method = "GET" }`),
    with the same `{name}` as the registered route.

### Example: `examples/aws-serverless/schedule-openai`

- Management routes use the containerized paths:
  `GET /schedules`, `GET` / `PUT` / `DELETE /schedules/{task_id}`.
  - Task id comes from the path only, never the query or body.
  - `?user_id=` stays as the demo's stand-in for an authorizer.
- `deploy/main.tf`, `lambda_test.py` and `README.md` follow the new routes.

### Docs and skills

- `docs/docs/deployment/aws-serverless.md`: a "Path and query parameters" section (usage,
  `gateway_endpoints`, the precedence rule, the overlap warning, API Gateway REST only) and the
  scheduling management routes on Lambda.
- `docs/docs/advanced/scheduling.md`: how management routes are served on Lambda.
- `ak-py/src/agentkernel/skills/ak-cloud-deploy/SKILL.md`: the serverless schedule routes.
- `Lambda.register` and `RESTLambdaRouter` docstrings mention path parameters.

## Non-goals

- Phase 2 of #879: `ThreadLambdaHandler` and the thread read routes on Lambda.
- Route authorization on any cloud.
- Our own template matcher, or `{proxy+}`-to-route mapping inside the router.
- HTTP API v2 / Function URL (payload 2.0) events: they carry no `resource`, so only static routes
  match there (unchanged).
- Moving the chat endpoint check onto `resource` (it would change custom-domain behaviour; out of scope).
- GCP and Azure.

## Open questions

- None. Settled during implementation:
  - Resource first with path fallback, rather than swapping `event_path` to prefer `resource`:
    the swap would break chat and every custom route behind a `{proxy+}` resource.
