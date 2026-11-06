# #879 (phase 1): Path-parameter routing in the Lambda REST router — Implementation Spec

`RESTLambdaRouter.dispatch()` resolves a non-chat request's route key from the resource template
API Gateway matched, falling back to the concrete path. Requirements source: [design.md](design.md).

## Design

### `RESTLambdaRouter._resolve_route_path` (new private method)

`ak-py/src/agentkernel/deployment/aws/serverless/core/router/rest_lambda.py`

```python
def _resolve_route_path(self, event: dict[str, Any], event_path: str, base_path: str, method: str) -> str:
    # candidates in priority order: the matched template, then the concrete path; a missing resource is skipped
    candidates = [p.removeprefix(base_path) for p in (event.get("resource"), event_path) if p]
    # first candidate registered for the method; else the concrete path, so the no-match error is unchanged
    return next((p for p in candidates if method in self._routes.get(p, {})), candidates[-1])
```

Rules:

1. **The router never matches paths.** It looks keys up in `_routes`; API Gateway chose the template.
2. **Resource before path.** When both are registered (a template and a concrete path that equals the
   request), the gateway's choice wins, so code and gateway cannot disagree.
3. **Path is the fallback and the default.** An unregistered `resource` (`/{proxy+}`) or a missing one
   falls through to the concrete path, which is the pre-change key.
4. **Method-aware.** A template registered for `GET` only does not capture a `DELETE`; the `DELETE`
   falls through to the path and fails as before.

`event_path` is never empty (`dispatch()` defaults it to `"/"`), so `candidates` always has at least
one entry and `candidates[-1]` is safe.

### `RESTLambdaRouter.dispatch` (changed)

- The non-chat branch calls `self._resolve_route_path(event, event_path, env_base_path, method)` in
  place of `event_path.removeprefix(env_base_path)`.
- Everything else is unchanged: method normalization, `event_path` derivation, the chat endpoint
  check, the no-env-vars branch, the lookup, the error message and the handler call.

### Docstrings

- `RESTLambdaRouter` class docstring: routes may carry path parameters, looked up by the resource
  template; values in `event["pathParameters"]`.
- `Lambda.register` (`aklambda.py`): the `route` param may carry path parameters.

### Example: `examples/aws-serverless/schedule-openai`

| File | Change |
|---|---|
| `lambda_request_handler.py` | `get_schedule` / `amend_schedule` / `cancel_schedule` registered on `/schedules/{task_id}` for `GET` / `PUT` / `DELETE`; read `event["pathParameters"]["task_id"]`; PUT body is the amendment only; `user_id` from `?user_id=` via `_user_id()` |
| `deploy/main.tf` | `gateway_endpoints`: `schedules` GET, `schedules/{task_id}` GET / PUT / DELETE |
| `lambda_test.py` | client uses `GET` / `PUT` / `DELETE {schedules_url}/{task_id}` with `params={"user_id": ...}` |
| `README.md` | diagram, route table (now identical to containerized), curl examples, ownership note |

### Config changes

No config changes. No `AKConfig` field, env var or Terraform variable is added or changed.

### Behavioural changes

1. **Template routes dispatch** (intentional, the feature). Before: `ValueError` → 500.
2. **The gateway's template beats a registered concrete path** when both exist (intentional, rule 2).
   Before: the concrete path won. Only reachable when a route is registered in code but absent from
   `gateway_endpoints`.
3. **Example routes change** (intentional): `/schedules/get`, `/schedules/amend`, `/schedules/cancel`
   are removed in favour of `/schedules/{task_id}`. Clients of the example must update.

**Non-changes:** `register()` signature and normalization; `_routes` shape; chat and poll routing;
the no-env-vars fallback; the no-match error text; `Lambda._wrap_response`; the Terraform module;
`APIGatewayAuthorizer` and `WebhookRouteMatcher` (they match on method and path, untouched);
`LambdaWebhookHost` routes (static paths).

## Error handling

- No registered template or path for the method → the existing `ValueError("No registered route found
  for API Gateway path -> '<concrete path>' and method '<method>'")`, turned into a 500 by
  `Lambda.handler`.
- A handler reading `event["pathParameters"]` on a template route always finds the key: API Gateway
  only sets that `resource` when it matched the template, and so filled the parameters.

## Testing

`ak-py/tests/test_lambda_router.py`:

- `make_event_with_env_vars` takes `**extra` so tests can add `resource` / `pathParameters`; existing
  callers are unchanged.
- New tests:
  - `test_dispatch_routes_path_parameter_route_by_resource_template`: template dispatches; handler
    reads `pathParameters`.
  - `test_dispatch_follows_the_resource_api_gateway_selected_over_a_matching_concrete_path`: rule 2.
  - `test_dispatch_routes_static_route_when_resource_equals_path`: static beats template.
  - `test_dispatch_falls_back_to_concrete_path_when_resource_is_not_registered`: `{proxy+}`.
  - `test_dispatch_raises_when_template_route_lacks_the_method`: rule 4, error names the concrete path.
  - `test_dispatch_routes_agent_endpoint_to_default_when_resource_is_present`: chat unchanged.
- Existing tests (events without `resource`) pass unchanged.

Run: `cd ak-py && uv run pytest tests/test_lambda_router.py tests/test_authorizer_webhook_bypass.py`.

The example's `lambda_test.py` is an integration test against a deployed stack (weekly matrix); it
is not run locally.
