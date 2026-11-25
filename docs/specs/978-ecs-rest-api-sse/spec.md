# #978: ECS — replace the API Gateway HTTP API with a REST API so SSE can stream — Implementation Spec

Implements the requirements in [`design.md`](design.md). The ECS module's non-WebSocket gateway stops
being an `aws_apigatewayv2_api` and becomes an `aws_api_gateway_rest_api` whose definition is a single
OpenAPI 3.0 document rendered from the existing `local.gateway_endpoints_map`, with
`responseTransferMode: STREAM` and an HTTP-proxy private integration that reaches the existing ALB
directly over the existing VPC link V2. Everything is Terraform under
`ak-deployment/ak-aws/containerized/`; no Python changes.

The renderer is modelled on `ak-gcp/containerized/api_gateway.tf`, which already turns the same
`gateway_endpoints_map` into an OpenAPI document. Resource conventions (endpoint type, stage name,
separate deployment + stage, hash-driven redeployment) follow
`ak-aws/serverless/modules/api-gateway/main.tf`.

**Read first:** [§0 Extension keys and the two timeouts](#0-extension-keys-and-the-two-timeouts) —
decision 6's approach is confirmed implementable, and the same check turned up a second timeout the
design did not account for.

---

## 0. Extension keys and the two timeouts

Claim 1 confirmed `response_transfer_mode` and `integration_target` as **arguments on
`aws_api_gateway_integration`** — a resource this spec does not use, because decision 6 builds the API
from an OpenAPI `body`. What that needs instead are the matching **extension keys** inside
`x-amazon-apigateway-integration`.

**Both exist** — `research/aws-claims-to-verify.md` claim 5, confirmed from the
[extension reference](https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-swagger-extensions-integration.html),
which enumerates every supported key:

- `integrationTarget` — "The ALB or NLB ARN to send the request to. **Supported only for private
  integrations that use VPC links V2.**" That description is claim 2's mechanism stated as
  documentation, so the ALB-direct arrangement is the documented one rather than a hopeful reading.
- `responseTransferMode` — `BUFFERED` or `STREAM`, where `STREAM` sends "partial responses back to the
  client as they become available".

AWS's own worked example on
[response-streaming-http](https://docs.aws.amazon.com/apigateway/latest/developerguide/response-streaming-http.html)
is an OpenAPI 3.0.1 document imported with `endpointConfigurationTypes=REGIONAL` — the exact shape §2
and §3 build. **Decision 6 stands; no throwaway apply is needed.**

### The finding that does change this spec: `timeoutInMillis`

The same reference states the ordinary integration timeout range as "between 50 ms and 29,000 ms".
`design.md` never mentioned the key, and **leaving it unset takes the 29 s default, capping every SSE
stream at 29 seconds** — the HTTP API's failure reproduced from a different cause.

Two caps now exist on the request path, limiting different things:

| Cap | Limits | Variable | Default |
| --- | --- | --- | --- |
| ALB `idle_timeout` | a **silent gap** between bytes | `alb_idle_timeout` | 300 s |
| Integration `timeoutInMillis` | **total** integration duration | `gateway_integration_timeout` | 900 s |

A stream emitting a chunk every two seconds for ten minutes never trips the ALB and is killed by the
integration timeout, which is why one variable cannot cover both.

**Both defaults are provisional.** AWS contradicts itself on one page: the streaming guide says the
timeout is configurable "up to 15 minutes" and its example sets `timeoutInMillis: 900000`, while the
`BUFFERED` → `STREAM` switch says a customised timeout "is removed, as API Gateway streams your
response for up to 5 minutes". 900 follows the example. Claim 4b measures it, and the 300 s
`alb_idle_timeout` default is resettled at the same time — it was chosen to match "the REST API's
stated idle limit", and that 5-minute figure turns out to describe the *total* duration, not an idle
one.

---

## Design

### 1. Endpoint normalisation (`state.tf`)

#### 1.1 A correction to `design.md`

`design.md:82-83` states that `local.gateway_endpoints_map`'s construction is unchanged. **It cannot
be**, and the reason is a latent inconsistency the HTTP API never exposed.

The map's `path` field means two different things depending on which branch built the entry:

| Entry | `path` value | Shape |
| --- | --- | --- |
| `default_gateway_endpoint` (`state.tf:31`) | `local.default_endpoint_path` | absolute — `/api/v1/chat` |
| `multipart_gateway_endpoint` (`:37`) | `local.multipart_endpoint_path` | absolute |
| `user_gateway_map` (`:50-57`) | the raw user object | **relative** — `schedules/{task_id}` |
| `mcp_gateway_map` (`:59-65`) | `"mcp"` | **relative** |

The HTTP API never noticed because `api_gateway.tf` reads only `each.key` (which always carries the
full path) and `each.value["overwrite_path"]`. Verified: those are the map's only two consumers
(`api_gateway.tf:30`, `:44`), and **no Terraform in the module reads `.path` at all**.

An OpenAPI renderer must key its `paths` object by the external path, so it needs `path` to mean one
thing. Deriving it from the map key instead is not viable — `split(" ", key)` has no safe behaviour on
the pre-existing `"$default"` key (`state.tf:53`), and inferring absoluteness from a leading `/` breaks
the legitimate user input `path = "/schedules"`, which `trim(..., "/")` handles correctly today.

**Resolution:** normalise `path` to the full external path in every branch, exactly as the GCP module
already does (`ak-gcp/containerized/state.tf:116`, `:126`). This is invisible to the rest of the
module because nothing reads the field, and it removes a divergence from GCP rather than adding one.

```hcl
  user_gateway_map = {
    for ep in var.gateway_endpoints :
    (
      lower(try(ep["method"], "")) == "$default"
      ? "$default"
      : "${upper(try(ep["method"], "ANY"))} ${local.user_endpoint_paths[ep.path]}"
    ) => {
      path           = local.user_endpoint_paths[ep.path]
      method         = try(ep["method"], "ANY")
      overwrite_path = try(ep["overwrite_path"], null)
    }
  }
```

with the path join lifted into its own local so the key and the field cannot drift:

```hcl
  user_endpoint_paths = {
    for raw in distinct([for ep in var.gateway_endpoints : try(ep["path"], "")]) :
    raw => join("/", compact([local.api_base_segment_with_version, trim(raw, "/")]))
  }
```

`distinct()` is **required, not tidiness.** Iterating `var.gateway_endpoints` directly and keying on
`ep.path` fails whenever two endpoints share a path with different methods, which is legal input the
`gateway_endpoints` validation does not forbid: Terraform rejects it with `Duplicate object key:
duplicates are expected, use the ellipsis (...) after the value expression`. Verified by evaluating
both forms in `terraform console` against two endpoints on one path (`GET` and `POST /reports`).

and `mcp_gateway_map`'s `path` set to `local.mcp_endpoint_path` rather than `"mcp"`.

> **Reviewer action:** `design.md`'s Route translation section needs its first bullet corrected — the
> inputs feeding the map are unchanged, but the map's own `path` field is normalised. Nothing else in
> the design moves.

#### 1.2 The `rest_async` poll route joins the endpoint set

`api_gateway_async.tf` is deleted. Its route becomes an ordinary entry in a new local, so the renderer
needs no special case and the grouping in §1.5 handles it as it handles any path with two methods —
which is the point `design.md:116-118` makes.

```hcl
  # rest_async polling: GET on the default chat path reads a stored reply. Its backend path is the
  # hardcoded /api/v1/chat, not the external path — the external path is the same one the default
  # POST serves, so this is a second method on one path, not a second path.
  poll_gateway_endpoint = {
    path           = local.default_endpoint_path
    method         = "GET"
    overwrite_path = "/api/v1/chat"
  }

  rest_endpoints_map = merge(
    local.gateway_endpoints_map,
    var.queue_mode && var.execution_mode == "rest_async" ? {
      "GET ${local.default_endpoint_path}" = local.poll_gateway_endpoint
    } : {},
  )
```

This mirrors `ak-gcp/containerized/state.tf:94-98`, `:107-109` field for field, including the
`overwrite_path` value. Placing it in `rest_endpoints_map` rather than inside `default_gateway_map`
keeps `gateway_endpoints_map` serving exactly the endpoints it serves today, so the v2 resources
removed in §2 and the new ones can be reasoned about against the same input.

### 2. The OpenAPI document (`api_gateway.tf`)

All of §2 is new content in `api_gateway.tf`, replacing lines 1–48 and 58–89 of the current file.
`aws_apigatewayv2_vpc_link.ecs_alb` (`:21-27`) stays byte for byte, including its
`"${var.prefix}-httpapi-vpclink"` name — changing the name forces replacement of a link this change
exists to reuse.

#### 2.1 Parameter translation

One regular expression recognises all three HTTP-API parameter-mapping sources in `overwrite_path`,
bare or braced:

```hcl
  # $request.path.x / ${request.header.x} / $request.querystring.x — the three sources HTTP API
  # parameter mapping accepts in overwrite:path. Terraform's regex engine is RE2: no lookarounds, so
  # the name's character class carries the right-hand boundary (it excludes "/" and "}").
  _param_re = "\\$\\{?request\\.(path|header|querystring)\\.([A-Za-z0-9_-]+)\\}?"
```

Per endpoint:

```hcl
  _eps = {
    for key, ep in local.rest_endpoints_map :
    key => {
      ext_path = ep.path
      method   = lower(try(ep.method, "ANY"))
      is_any   = lower(try(ep.method, "ANY")) == "any"

      # Mapped parameters found in overwrite_path: [[source, name], ...]
      mapped = regexall(local._param_re, try(ep.overwrite_path, ""))

      # Path template parameters in the EXTERNAL path. API Gateway rejects an import whose path
      # template declares {x} that the operation does not list in `parameters`, so these are
      # required whether or not overwrite_path references them.
      templated = [for m in regexall("\\{([A-Za-z0-9_-]+)\\+?\\}", ep.path) : m[0]]

      # The integration URI's path: each expression becomes a {name} placeholder.
      backend_path = replace(try(ep.overwrite_path, ""), "/${local._param_re}/", "{$2}")
    }
  }
```

Notes on the mechanics, each of which is a thing that silently does the wrong thing if written
differently:

- `regexall` with capture groups returns a list of lists, so `m[0]` is the source
  (`path`/`header`/`querystring`) and `m[1]` the name.
- `replace`'s second argument must be wrapped in `/.../` to be treated as a regex rather than a
  literal; `$2` is the name group. `"{$2}"` is safe in HCL — interpolation needs `${`, and here `$`
  is followed by `2`.
- `templated` strips a trailing `+` so a greedy `{proxy+}` segment declares the parameter `proxy`,
  which is how API Gateway names it.
- `method` is lowercased for the OpenAPI key; `requestParameters` and `parameters` use the
  **unmodified** parameter names, which are case-sensitive.

The two derived collections, with the external path template taking precedence over an
`overwrite_path`-derived entry of the same name:

```hcl
  _ep_params = {
    for key, ep in local._eps :
    key => concat(
      [for n in ep.templated : {
        name     = n
        in       = "path"
        required = true
        schema   = { type = "string" }
      }],
      [for m in ep.mapped : {
        name     = m[1]
        in       = m[0] == "querystring" ? "query" : m[0]
        required = true
        schema   = { type = "string" }
      } if !contains(ep.templated, m[1])],
    )
  }

  # The integration's {name} placeholders are always integration.request.path.*; only the SOURCE
  # differs. AWS spells the query source "querystring" here while OpenAPI's `in` says "query".
  _ep_request_params = {
    for key, ep in local._eps :
    key => {
      for m in ep.mapped :
      "integration.request.path.${m[1]}" => "method.request.${m[0]}.${m[1]}"
    }
  }
```

`design.md:87-104` requires exactly this: a `{name}` segment in the integration `uri`, a method-level
`parameters` entry with the matching `in`, and a `requestParameters` line. The `templated` half is
additional and non-optional — it is what makes the `ANY /api/v1/schedules/{task_id}` example importable
at all.

#### 2.2 Operation objects

Every operation has the same shape, which is why this renderer needs none of the per-method splitting
the GCP file carries (`ak-gcp/containerized/api_gateway.tf:61-127` exists only because
`x-google-allow` paths have a different shape from the rest). Terraform's type checker is satisfied by
one builder:

```hcl
  _ep_operations = {
    for key, ep in local._eps :
    key => {
      summary     = "Route to ${ep.ext_path}"
      operationId = "${replace(ep.method, "any", "any-method")}-${replace(trim(ep.ext_path, "/"), "/", "-")}"
      parameters  = local._ep_params[key]
      responses   = { "200" = { description = "Success" } }
      "x-amazon-apigateway-integration" = {
        type                 = "http_proxy"
        httpMethod           = "ANY"
        connectionType       = "VPC_LINK"
        connectionId         = one(aws_apigatewayv2_vpc_link.ecs_alb[*].id)
        integrationTarget    = module.rest_service.alb_arn
        uri                  = "http://${module.rest_service.alb_dns_name}${ep.backend_path}"
        responseTransferMode = "STREAM"
        timeoutInMillis      = var.gateway_integration_timeout * 1000
        passthroughBehavior  = "when_no_match"
        requestParameters    = local._ep_request_params[key]
      }
    }
  }
```

- `integrationTarget` is the **load balancer** ARN (`modules/rest-service/outputs.tf:21`), not the
  listener ARN the v2 integration used (`api_gateway.tf:34`). The listener ARN is no longer
  referenced anywhere outside WebSocket mode; `alb_listener_arn` stays as a module output because
  nothing else needs it removed.
- `httpMethod = "ANY"` is the **integration's** method, meaning "forward whatever the caller used". It
  is unrelated to the operation's own key and is required on every operation including `get`.
- `connectionId` uses `one(...[*].id)`, not `[0].id`. In a WebSocket mode the link has `count = 0`,
  and `[0]` on it raises `Invalid index` the moment anything evaluates the local. Every consumer is
  itself `count = 0` there, so Terraform's laziness *should* mean it is never evaluated — but a
  plan-time crash in WebSocket mode is the one failure this change must not have (`design.md:284`),
  and with no state it cannot be reproduced locally. `one()` returns `null` for an empty collection,
  so the hazard is removed rather than reasoned about.
- `timeoutInMillis` is **not optional** (§0). The variable is in seconds for consistency with
  `alb_idle_timeout`; the `* 1000` lives here, at the one place the millisecond unit is required.
- `operationId` must be unique across the document. `replace(ep.method, "any", "any-method")` keeps the
  ANY operation distinct from a sibling `get` on the same path; `trim`/`replace` on the path mirror
  GCP's `operationId` construction (`ak-gcp/containerized/api_gateway.tf:77`). A path containing
  `{task_id}` yields `any-method-api-v1-schedules-{task_id}`, which is unique and which API Gateway
  accepts.

#### 2.3 Method keys and per-path grouping

```hcl
  _method_key = {
    for key, ep in local._eps :
    key => ep.is_any ? "x-amazon-apigateway-any-method" : ep.method
  }

  # One path object per external path, carrying every method served on it. The rest_async poll route
  # is why this groups rather than emitting one path per route key: GET and POST share the default
  # chat path.
  openapi_paths_block = {
    for path in distinct([for ep in values(local._eps) : ep.ext_path]) :
    path => merge(concat(
      [for key, ep in local._eps : { (local._method_key[key]) = local._ep_operations[key] } if ep.ext_path == path],
      [for p, op in local._options_op : { options = op } if p == path],
    )...)
  }
```

`x-amazon-apigateway-any-method` replaces the method name as a key in the path object — OpenAPI has no
`any` key, which is `design.md:86`.

#### 2.4 CORS preflight operations

Per `design.md:121-130`: an `OPTIONS` operation only on paths with no any-method (which already accepts
`OPTIONS`), and **proxied to the container, not mocked**, because `CORSMiddleware` already answers
preflight (`ak-py/src/agentkernel/api/http.py:55-61`).

```hcl
  # One preflight per path, routed through the path's first non-ANY endpoint. Map iteration is in
  # key order, so the choice is stable across plans.
  _non_any_by_path = {
    for key, ep in local._eps : ep.ext_path => ep... if !ep.is_any
  }

  _options_op = {
    for path, eps in local._non_any_by_path :
    path => {
      summary     = "CORS pre-flight for ${path}"
      operationId = "options-${replace(trim(path, "/"), "/", "-")}"
      parameters  = [for n in eps[0].templated : { name = n, in = "path", required = true, schema = { type = "string" } }]
      responses   = { "200" = { description = "CORS pre-flight" } }
      "x-amazon-apigateway-integration" = {
        type                = "http_proxy"
        httpMethod          = "OPTIONS"
        connectionType      = "VPC_LINK"
        connectionId        = one(aws_apigatewayv2_vpc_link.ecs_alb[*].id)
        integrationTarget   = module.rest_service.alb_arn
        uri                 = "http://${module.rest_service.alb_dns_name}${eps[0].backend_path}"
        passthroughBehavior = "when_no_match"
        requestParameters   = local._ep_request_params[keys({ for k, e in local._eps : k => e if e.ext_path == path && !e.is_any })[0]]
      }
    }
    if var.enable_cors
  }
```

**As implemented, the grouping local holds keys rather than endpoints** — `_non_any_keys_by_path`
with `key...` in place of `_non_any_by_path` with `ep...`. The version above has to recover the key a
second time for `requestParameters`, by re-running the same filter inside `keys({...})[0]`; grouping
the keys to begin with yields both the endpoint (`local._eps[ep_keys[0]]`) and its request parameters
from one lookup. Same result, same stable key ordering, one filter.

This is `ak-gcp/containerized/api_gateway.tf:42-59` with AWS extension keys. Two deliberate
differences from the sibling operations: `httpMethod` is `OPTIONS` rather than `ANY`, since this
operation forwards only preflight; and both `responseTransferMode` and `timeoutInMillis` are omitted,
because a preflight response is a few headers — it has nothing to stream and returns well inside the
29 s default.

`var.enable_cors` keeps its one remaining effect — whether the preflight operation is emitted at all.
The `cors_allow_*` variables have none, which §"Behavioural changes" records.

#### 2.5 The document root

```hcl
  openapi_spec = {
    openapi = "3.0.1"
    info = {
      title       = "${var.product_display_name} API"
      description = "[${var.prefix}] ${var.product_display_name} REST API"
      version     = var.api_version
    }
    paths = local.openapi_paths_block
    # /chat-multipart bodies are corrupted silently without this (design.md:119-120).
    "x-amazon-apigateway-binary-media-types" = ["multipart/form-data"]
  }

  openapi_spec_json = jsonencode(local.openapi_spec)
```

OpenAPI 3.0.1 rather than Swagger 2.0 (GCP's version, forced by ESPv2): it is what API Gateway's own
export emits, and it is why `parameters` entries above carry `schema = { type = "string" }` rather
than a bare `type`.

### 3. REST API resources (`api_gateway.tf`)

```hcl
resource "aws_api_gateway_rest_api" "rest_api" {
  count       = local.is_websocket_mode ? 0 : 1
  name        = "${var.prefix}-rest-api-${var.region}"
  description = "[${var.prefix}] ${var.product_display_name} REST API"
  body        = local.openapi_spec_json

  # The body is the whole definition; "overwrite" makes an apply converge on it rather than merging
  # into whatever the last one left behind.
  put_rest_api_mode = "overwrite"

  endpoint_configuration {
    # REGIONAL, not EDGE: an edge-optimized endpoint keeps a 30 s streaming idle cap and would undo
    # this change silently. Matches serverless/modules/api-gateway/main.tf:40.
    types = ["REGIONAL"]
  }

  tags = var.tags
}

resource "aws_api_gateway_deployment" "rest" {
  count       = local.is_websocket_mode ? 0 : 1
  rest_api_id = aws_api_gateway_rest_api.rest_api[0].id

  triggers = {
    redeployment = sha1(local.openapi_spec_json)
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "agents" {
  count         = local.is_websocket_mode ? 0 : 1
  rest_api_id   = aws_api_gateway_rest_api.rest_api[0].id
  deployment_id = aws_api_gateway_deployment.rest[0].id
  stage_name    = "agents"

  # The account-level CloudWatch role must exist before the stage enables access logging.
  depends_on = [aws_api_gateway_account.this]

  dynamic "access_log_settings" {
    for_each = var.enable_api_gateway_logs ? [1] : []
    content {
      destination_arn = aws_cloudwatch_log_group.rest_api[0].arn
      format = jsonencode({
        requestId               = "$context.requestId"
        sourceIp                = "$context.identity.sourceIp"
        requestTime             = "$context.requestTime"
        protocol                = "$context.protocol"
        httpMethod              = "$context.httpMethod"
        resourcePath            = "$context.resourcePath"
        routeKey                = "$context.routeKey"
        status                  = "$context.status"
        responseLength          = "$context.responseLength"
        integrationErrorMessage = "$context.integrationErrorMessage"
      })
    }
  }

  tags = var.tags
}

resource "aws_api_gateway_method_settings" "throttling" {
  count       = !local.is_websocket_mode && var.throttling_rate_limit != null && var.throttling_burst_limit != null ? 1 : 0
  rest_api_id = aws_api_gateway_rest_api.rest_api[0].id
  stage_name  = aws_api_gateway_stage.agents[0].stage_name
  method_path = "*/*"

  settings {
    throttling_rate_limit  = var.throttling_rate_limit
    throttling_burst_limit = var.throttling_burst_limit
  }
}
```

Per-resource notes:

- **Stage name `agents`** and the separate deployment + stage both match
  `serverless/modules/api-gateway/main.tf:157`, `:128`. The log format is that module's format
  verbatim (`:170-181`) — it logs **both** `resourcePath` and `routeKey`, which is why this one keeps
  `routeKey` rather than replacing it (`design.md:233-235`).
- **`triggers`** hashes the rendered document rather than enumerating resource ids, because with a
  `body` there are no per-resource ids to enumerate. `sha1(local.openapi_spec_json)` is the body-shaped
  equivalent of serverless's `sha1(jsonencode([...resource ids...]))` (`:130-137`) and of GCP's
  `substr(md5(local.openapi_spec_json), 0, 8)` config id
  (`ak-gcp/containerized/api_gateway.tf:224`).
  - The document embeds `aws_apigatewayv2_vpc_link.ecs_alb[0].id` and
    `module.rest_service.alb_dns_name`, so on a **first** apply the hash is unknown until those exist
    and the deployment reads `(known after apply)`. On every apply after that both come from state and
    the hash is stable, so an unchanged endpoint set produces no diff. GCP has the identical property
    (`local.service_url` is the Cloud Run service's URI), so this is a known-good shape, not a new
    risk.
- **`aws_api_gateway_method_settings`** has **no precedent in this repo** — verified: the serverless
  module has no throttling of any kind. It is the only way a REST API expresses what
  `default_route_settings` expressed on the v2 stage (`api_gateway.tf:64-70`); REST stages carry no
  inline throttle block. `method_path = "*/*"` is the all-methods-all-resources wildcard, matching
  `default_route_settings`' scope.
- **`depends_on`** copies the WebSocket stage's line (`api_gateway_ws.tf:109`) for the reason stated
  there and in `design.md:201-202`.

#### 3.1 The CloudWatch log group keeps its AWS name

The Terraform address moves from `aws_cloudwatch_log_group.http_api` to `.rest_api`, but the **AWS log
group name string stays `/aws/apigateway/${var.prefix}-http-api`**. A rename would destroy the group
and its retained access logs for no functional gain; the stale `-http-api` in an AWS resource name is
cosmetic, and the Terraform address a reader works with is the one that gets fixed.

The address move is handled by a `moved` block so no user runs `terraform state mv`:

```hcl
moved {
  from = aws_cloudwatch_log_group.http_api
  to   = aws_cloudwatch_log_group.rest_api
}
```

Its `count` gate is unchanged: `var.enable_api_gateway_logs && !local.is_websocket_mode`.

### 4. The account-level CloudWatch role (`api_gateway_ws.tf`)

Three `count` expressions are relaxed from `local.is_websocket_mode && var.enable_api_gateway_logs` to
`var.enable_api_gateway_logs` alone, per `design.md:194-200`:

| Resource | Line | New `count` |
| --- | --- | --- |
| `aws_iam_role.apigw_cloudwatch` | `api_gateway_ws.tf:74` | `var.enable_api_gateway_logs ? 1 : 0` |
| `aws_iam_role_policy_attachment.apigw_cloudwatch` | `:90` | same |
| `aws_api_gateway_account.this` | `:96` | same |

- Nothing else in those blocks changes, so **the state addresses do not move** — an existing WebSocket
  deployment with logging on plans clean with no replacement and no `terraform state mv`. This is an
  explicit acceptance criterion (`design.md:284`).
- Each is a single `count = 0/1` resource, so a deployment creates at most one of each however many
  stages consume it. The relaxation therefore does not depend on the modes being mutually exclusive —
  which matters, because #985 would serve a REST stage beside the WebSocket one.
- The three resources stay in `api_gateway_ws.tf`. Moving them to a file of their own would be
  tidier and is deliberately **not** done: a file move with no address change is pure review noise,
  and the comment at `:72` already explains the singleton.

### 5. Deleted: `api_gateway_async.tf`

The whole file goes. Its integration and route are replaced by `local.poll_gateway_endpoint`
(§1.2) flowing through the ordinary renderer. The `local.api_base_segment_with_version` reference at
`:23` was its only consumer outside `state.tf`.

### 6. Request-path timeouts

Two variables, one per cap (§0). They are declared in different places because they act in different
places: the ALB one is a property of the load balancer and so belongs to `modules/rest-service/`, while
the gateway one is read only by the renderer in §2.2 and so lives on the root module alone.

```hcl
# variables.tf (root module only — modules/rest-service/ never sees it)
variable "gateway_integration_timeout" {
  type        = number
  description = <<-EOT
    Seconds API Gateway allows one integration request to run in total, including a streamed
    response. Caps the length of an SSE stream. Distinct from alb_idle_timeout, which bounds a silent
    gap rather than the total: a stream emitting steadily for longer than this is cut even though the
    ALB never sees an idle period.
  EOT
  default     = 900
}
```

Both this description and §6.1's ship as **single-line strings**, not heredocs. The heredocs here are
for readability in this document only: `ak-deployment/` contains no `description = <<` anywhere, and
its single-line descriptions already run to 573 characters, so a heredoc would be a new convention
introduced for two variables.

Consumed only as `var.gateway_integration_timeout * 1000` in the operation builder (§2.2). No
validation block: AWS rejects an out-of-range value at import, and the documented range under `STREAM`
is exactly what claim 4b exists to establish — a `validation` written against today's contradictory
documentation would be guesswork hardened into a plan-time error.

#### 6.1 ALB idle timeout (`modules/rest-service/`)

```hcl
# modules/rest-service/variables.tf
variable "alb_idle_timeout" {
  type        = number
  description = <<-EOT
    Seconds the ALB holds a connection open with no bytes in either direction, before closing it.
    Raise it when an agent can stay silent mid-stream for longer than the default — a long tool call
    under SSE. The gateway's own idle limit caps the end-to-end stream, so raising this alone does
    not extend a stream past what API Gateway allows.
  EOT
  default     = 300
}
```

```hcl
# modules/rest-service/main.tf, in resource "aws_lb" "app" (:219)
  idle_timeout = var.alb_idle_timeout
```

and passed through from `rest_service.tf`:

```hcl
  alb_idle_timeout = var.alb_idle_timeout
```

with the same variable declared on the root module (`variables.tf`), same type, same default, same
description. A variable rather than a constant because every sibling target exposes its request-path
timeout that way (`design.md:136-142`); the default follows the measured idle limit if claim 4
contradicts the documented 300 s.

The current `aws_lb.app` sets no `idle_timeout` at all and so takes the AWS default of 60 s.
**Applying this change alters an existing ALB in place** — no replacement, but a live behaviour change
for every containerized deployment, including ones with no interest in SSE. Recorded under
Behavioural changes.

### 7. Response store wiring

#### 7.1 The env vars (`modules/rest-service/main.tf`)

Two entries in `local.rest_service_environment`, next to the DynamoDB one at `:37-40` and under the
same gate, because the response store exists only in REST queue modes:

```hcl
    # Response store is only used in REST queue modes (not WebSocket). Terraform injects the
    # connection detail only — AK_EXECUTION__RESPONSE_STORE__TYPE is never set, so config.yaml
    # selects the backend, exactly as with thread.type and schedule.store.type.
    (var.queue_mode && !var.websocket_mode) ? merge(
      { AK_EXECUTION__RESPONSE_STORE__DYNAMODB__TABLE_NAME = var.response_store_table_name },
      var.redis_url != null ? { AK_EXECUTION__RESPONSE_STORE__REDIS__URL = var.redis_url } : {},
      var.valkey_url != null ? { AK_EXECUTION__RESPONSE_STORE__VALKEY__URL = var.valkey_url } : {},
    ) : {},
```

- `var.redis_url` / `var.valkey_url` are **already** variables on this module
  (`modules/rest-service/variables.tf:59`, `:65`) and already wired from `rest_service.tf:22-23`. No
  new plumbing: the module has the values and currently uses them only for
  `AK_SESSION__REDIS__URL` / `AK_SESSION__VALKEY__URL` (`main.tf:4-9`).
- Both sub-blocks exist in the config model: `_ResponseStoreConfig.redis` and `.valkey`
  (`ak-py/src/agentkernel/core/config.py:681-682`), typed `_ResponseStoreRedisConfig` /
  `_ResponseStoreValkeyConfig` (`:658`, `:662`), each a `_RedisConfig` / `_ValkeyConfig` subclass that
  overrides only `prefix`. Pattern 2 is met with no new model and no new field.
- **The agent runner gets neither.** `modules/agent-runner/main.tf` injects only
  `AK_SESSION__REDIS__URL` / `AK_SESSION__VALKEY__URL` (`:14-15`) and has no response-store variable
  at all — verified. That is correct and is not to be "fixed": the runner fans chunks onto the output
  queue, and both the store's writer and its reader live in the IO container
  (`design.md:179-186`).
- **Verify on the first deployment:** that an env-injected
  `AK_EXECUTION__RESPONSE_STORE__REDIS__URL` merges with a `config.yaml` that sets
  `execution.response_store.type: redis`, rather than the YAML block replacing the env value. The
  module already depends on this direction working for `AK_SESSION__REDIS__URL` beside a
  `session.type: redis`, so the mechanism is in use — but `response_store` is
  `_ResponseStoreConfig | None = None` (`:941`), so here the env var must materialise two nested
  levels, not one. Confirm it before trusting requirement (a).

#### 7.2 The outputs (`outputs.tf`)

```hcl
output "redis_url" {
  description = "Connection URL of the module-created Redis cluster; null unless create_redis_cluster"
  value       = local.redis_url
}

output "valkey_url" {
  description = "Connection URL of the module-created Valkey cluster; null unless create_valkey_cluster"
  value       = local.valkey_url
}
```

Both locals already exist (`state.tf:10-11`). These are additive — nothing is renamed — and exist so a
caller can point an external component at the same store.

#### 7.3 The plan-time warning (`variables.tf` or a new `checks.tf`)

A `check` block, not a `validation`, following `check "scheduling_requires_queue_mode"`
(`eventbridge.tf:6-11`) in shape: a named check, one `assert`, an `error_message` opening
`[IMPORTANT]`.

```hcl
check "sse_requires_streaming_response_store" {
  assert {
    condition = !(var.queue_mode && var.execution_mode == "rest_sync" && var.message_type == "delta") || (
      var.create_redis_cluster || var.create_valkey_cluster
    )
    error_message = "[IMPORTANT] SSE (execution_mode = \"rest_sync\" with message_type = \"delta\") needs a response store that can stream chunks. This deployment creates neither a Redis nor a Valkey cluster, so unless execution.response_store in config.yaml points at an external Redis or Valkey, the service will fail at startup. Set create_redis_cluster = true or create_valkey_cluster = true."
  }
}
```

**Corrected at implementation — no new file.** This section originally called for a `checks.tf`. The
repo has three `check` blocks and not one of them lives in a file of its own: `eventbridge.tf:6` sits
at the top of the file that creates the scheduling resources, and `serverless/state.tf:398`, `:467`
both sit beside what they guard. The check therefore goes in **`state.tf`**, immediately above
`module "redis"` / `module "valkey"` — the very resources `create_redis_cluster ||
create_valkey_cluster` tests, and the same file serverless keeps its checks in. The scheduling check
stays where it is.

Why a warning and not a rejection, restating `design.md:165-172` so the implementer does not
"improve" it into a `validation`: Terraform never sees which store `config.yaml` selected — the module
injects URLs only, never `AK_EXECUTION__RESPONSE_STORE__TYPE`. A hard rejection would **block** a valid
deployment pointing at an external Redis with no module cluster, and would **pass** one that created a
cluster but selects `dynamodb`. Enforcement stays at gate 4
(`ak-py/src/agentkernel/pipeline/io_handler.py:231-241`), which reads the resolved config at startup
and is the only place the real answer exists.

### 8. Removing the ECS SSE rejection (`variables.tf`)

- **Delete** the `message_type` validation at `:284-287` (gate 2) in full.
- **Reword** the `message_type` description (`:278`): drop `SSE is rejected with queue_mode = true.`
  The rest of the sentence stands.
- **Reword** "HTTP API" where it names the gateway type: `:47` (`gateway_endpoints`' description),
  `:181` (the `# CORS configuration for HTTP API (API Gateway v2)` comment), `:184`
  (`enable_cors`'s description) and `:240` (`enable_api_gateway_logs`'s description). The `enable_cors`
  and CORS-comment rewordings must also say what §2.4 and Behavioural changes below establish — that
  the flag now controls only whether a preflight operation is emitted.
- **Leave alone:** the `"$default"` entry in the `gateway_endpoints` method validation (`:60`) and its
  error message (`:63`). It is unmatchable by construction — `upper(ep.method)` can never equal the
  lowercase `"$default"` — and it is pre-existing (`design.md:105-106`).

### Consumer changes

| Consumer | Change |
| --- | --- |
| `api_gateway.tf:1-48`, `:58-89` | Deleted and replaced (§2, §3). `aws_apigatewayv2_vpc_link.ecs_alb` (`:21-27`) survives untouched |
| `api_gateway.tf:51-56` (log group) | `moved` to `.rest_api`; AWS name and `count` unchanged (§3.1) |
| `api_gateway_async.tf` | Deleted (§5) |
| `api_gateway_ws.tf:74`, `:90`, `:96` | `count` relaxed (§4). Everything else in the file **verified unchanged**, including the v2 WS API, the NLB-backed V1 VPC link at `:32`, and the WS stage |
| `state.tf:50-65` | `path` normalised (§1.1); `rest_endpoints_map` and `poll_gateway_endpoint` added (§1.2) |
| `variables.tf` | Gate 2 deleted, three descriptions reworded, `alb_idle_timeout` and `gateway_integration_timeout` added (§6, §8) |
| `outputs.tf:9-32` | Four outputs repointed (below); `redis_url` / `valkey_url` added (§7.2) |
| `modules/rest-service/main.tf:37-40`, `:219` | Response-store env vars, `idle_timeout` (§6, §7.1) |
| `modules/rest-service/variables.tf` | `alb_idle_timeout` added (§6) |
| `rest_service.tf` | `alb_idle_timeout` passed through (§6) |
| `checks.tf` (new) | The response-store check (§7.3) |
| `iam.tf` | **Verified unchanged.** A VPC-link HTTP proxy integration needs no new permission, and the response-store policy at `:40-62` / `:116-119` is DynamoDB-only because Redis and Valkey are reached by network, not by IAM |
| `modules/agent-runner/` | **Verified unchanged** (§7.1) |

Outputs, repointed with names and types unchanged (`design.md:230-232`):

```hcl
output "api_gateway_id" {
  description = "REST API Gateway ID (REST/queue modes only; null in WebSocket modes)"
  value       = try(aws_api_gateway_rest_api.rest_api[0].id, null)
}

output "api_gateway_stage" {
  description = "REST API Gateway stage name (REST/queue modes only; null in WebSocket modes)"
  value       = try(aws_api_gateway_stage.agents[0].stage_name, null)
}

output "agent_invoke_url" {
  description = "HTTP agent invoke URL (REST/queue modes only; null in WebSocket modes)"
  value       = local.is_websocket_mode ? null : "${aws_api_gateway_stage.agents[0].invoke_url}/api/${var.api_version}/${var.agent_endpoint}"
}
```

- `aws_api_gateway_stage`'s attribute is **`stage_name`**, not `name`.
- `agent_invoke_url` gets simpler: a REST stage exposes `invoke_url` directly, so the v2 fallback
  expression at `outputs.tf:31` (which reconstructed the URL from `api_endpoint` because an
  auto-deploy stage's `invoke_url` could be absent) goes away. `aws_api_gateway_rest_api` has no
  `api_endpoint` attribute, so that branch could not have survived in any case.
- The hardcoded `/api/` in `agent_invoke_url` is **pre-existing and left as is** — it ignores
  `var.api_base_path`, so the output is already wrong for a non-default base path. Out of scope;
  worth its own issue.
- The two log-group outputs (`:19-27`) change only their resource reference, from
  `aws_cloudwatch_log_group.http_api` to `.rest_api`.
- `e2e/app/deploy/outputs.tf:2` builds `https://<id>.execute-api.<region>.amazonaws.com/<stage>` from
  the first two outputs. A REST API's invoke URL has that same shape, so only the id's value changes
  and the expression needs no edit.

### Config changes

**No `AKConfig` changes.** Nothing in `ak-py` is touched. `execution.mode` and
`execution.message_type` already express everything the feature needs, and the one new env var
(`AK_EXECUTION__RESPONSE_STORE__REDIS__URL`, plus the Valkey twin) addresses existing fields on
existing models — `_ResponseStoreRedisConfig` / `_ResponseStoreValkeyConfig`, reused whole. No new
model, no new selector, no `enabled` flag.

**Two new Terraform input variables**, both in seconds:

| Variable | Declared on | Type | Default | Why it cannot be derived |
| --- | --- | --- | --- | --- |
| `alb_idle_timeout` | root **and** `modules/rest-service/` | `number` | `300` | The module has no request-path timeout of any kind today. How long an agent may stay silent is a property of the user's workload, not of AWS |
| `gateway_integration_timeout` | root only | `number` | `900` | Same, for total stream duration. Unset, the integration takes AWS's 29 s default and SSE dies at 29 s (§0) |

Both defaults are provisional pending claim 4.

The response-store requirement adds no variable: it is expressed through the existing
`create_redis_cluster` / `create_valkey_cluster` flags.

**Existing YAML and `AK_*` env vars keep working unchanged.** The new env vars are additive and gated
on a cluster existing; a deployment that creates no Redis or Valkey cluster sees no new environment at
all.

### Behavioural changes

Each is intentional.

1. **The API id and invoke URL change.** Replacing an `aws_apigatewayv2_api` with an
   `aws_api_gateway_rest_api` is a create-and-destroy, so every registered webhook (Slack, WhatsApp,
   Messenger, …) points at a dead URL until re-registered. This is the change's one breaking effect;
   announcement is specified under Documentation.
2. **The ALB idle timeout rises from an implicit 60 s to 300 s for every containerized deployment**,
   not only SSE ones. Intentional — 60 s cuts a long tool call whatever the gateway allows. Accepted
   cost: an abandoned connection (closed laptop, killed tab) is held for the timeout rather than 60 s
   before the ALB reaps it.
3. **`cors_allow_origins` and the other `cors_*` variables stop having any effect.** A deployment that
   narrowed origins is no longer narrowed: the container answers every origin, with credentials.
   `var.enable_cors` keeps one effect only — whether a preflight operation is emitted. AWS documents
   both halves: an HTTP API "ignores CORS headers returned from your backend integration", while a
   REST API's proxy integration leaves the backend "responsible for returning the
   `Access-Control-Allow-Origin` … headers". Nothing breaks, because the variables default to `["*"]`
   (`variables.tf:186`), so only a deliberately restricted deployment changes. #1006 makes the
   container's own policy configurable, which is the actual fix.
4. **A greedy route no longer catches method misses on an explicit path.** A user-supplied
   `path = "{proxy+}"` with `method = "ANY"` passes validation today and becomes
   `ANY /api/v1/{proxy+}`. An HTTP API matches method and path together, so `GET /api/v1/chat` misses
   the default `POST /api/v1/chat` and falls through to the greedy route. A REST API matches the path
   first, selects the explicit `/api/v1/chat` resource, finds no `GET` method and returns 403 — the
   greedy sibling is never reached. Documented, not worked around: giving every explicit resource a
   fallback method would turn today's clean method-not-allowed into a silent catch-all. Nothing in
   `examples/` or `e2e/` uses `{proxy+}` and it is not documented as supported.
5. **`aws_api_gateway_account` now also reaches REST deployments.** A REST-mode deployment with
   `enable_api_gateway_logs = true` joins a known hazard: the role is a singleton per account and
   region, concurrent deployments contend over it, and disabling the toggle *destroys* the account
   role, which can affect other REST APIs in the account
   (`serverless/modules/api-gateway/README.md:76-77`). WebSocket deployments have always had this;
   this change widens who meets it.
6. **An `overwrite_path` referencing a path parameter the external path does not declare now fails at
   apply instead of 404ing at runtime.** `$request.path.task_id` with no `{task_id}` in the external
   path produces `method.request.path.task_id`, which API Gateway rejects on import. Today the same
   mistake applies cleanly and 404s on every call. A louder failure, earlier — an improvement, but a
   behaviour change for anyone currently living with the broken route.
7. **Access logs gain `$context.resourcePath` and keep `$context.routeKey`**, matching the serverless
   REST API's format (`serverless/modules/api-gateway/main.tf:177-178`).
8. **The first apply after upgrading shows the deployment as `(known after apply)`** because the body
   embeds the ALB DNS name and VPC link id. Subsequent plans are stable. Same property as GCP.

**Non-changes** — fixed, and a review finding if they move:

- `gateway_endpoints`' type and semantics, including `ANY` and `$request.*` path parameters. Verified
  against `examples/aws-containerized/openai-schedule/deploy/main.tf:72-83` (`ANY` plus
  `$request.path.task_id`) and `examples/aws-containerized/crewai/deploy/main.tf:18-29` (two plain
  `GET` routes).
- Every output name and type. Four are repointed; none is renamed, retyped or removed.
- `api_gateway_ws.tf`'s API, NLB, V1 VPC link and stage.
- State addresses of the three CloudWatch-role resources — no `terraform state mv` for existing
  WebSocket users.
- `aws_apigatewayv2_vpc_link.ecs_alb`'s address and name.
- The AWS name of the API Gateway log group.
- Everything in `ak-py`.

---

## Error handling

| Failure | Where it surfaces | Behaviour |
| --- | --- | --- |
| Unknown or malformed `x-amazon-apigateway-*` extension key | `terraform apply`, on `CreateRestApi`/`PutRestApi` | Import error naming the key. Every key this spec uses is in the AWS reference (§0), so this should only follow a typo |
| `overwrite_path` names a path parameter the external path does not declare | `terraform apply` | Import rejects the `method.request.path.*` mapping. See Behavioural change 6 |
| No Redis or Valkey cluster under SSE settings | `terraform plan`, as a **warning** | The `check` block (§7.3). Apply proceeds |
| Response store cannot stream chunks | Container startup | Gate 4 (`io_handler.py:231-241`) raises `AKConfigError`. **Kept** |
| Same, per request | The REST route | Gate 5 (`request_handler.py:561-569`) returns 400. **Kept** |
| Response store URL missing entirely | Nowhere | `_RedisConfig.url` defaults to `redis://localhost:6379` (`core/config.py:25`), so a task selecting `type: redis` silently points at its own loopback. This is the hole requirement (a) in §7.1 closes; nothing reports it |
| VPC link goes `INACTIVE` | Requests, as 5xx | Unchanged — the link is reused as is, not recreated |
| Account-level CloudWatch role contention | `terraform apply` | Unchanged in kind (Behavioural change 5) |
| A silent gap exceeds the ALB idle timeout | The connection drops mid-stream | Raise `alb_idle_timeout` |
| A stream runs longer than the integration timeout | The connection drops mid-stream, with the ALB idle timeout never reached | Raise `gateway_integration_timeout`, subject to whatever ceiling claim 4b establishes. **If `timeoutInMillis` is omitted this fires at 29 s** and looks exactly like the HTTP API's old behaviour (§0) |

Gates 4 and 5 stay exactly as they are and must still fire for a non-streaming store. Removing gate 2
(§8) moves the SSE-plus-wrong-store diagnosis from plan time to startup **on purpose** — plan time
cannot see which store `config.yaml` selects.

---

## Testing

The module has no Terraform unit tests and no `.tftest.hcl` files, so verification is
`terraform validate` / `plan` plus a real deployment. There are no Python tests to change, because no
Python changes.

### Static

Run from `ak-deployment/ak-aws/containerized/`:

```bash
terraform fmt -recursive -check
terraform init -backend=false
terraform validate
```

`validate` is the first real check on the renderer: Terraform's type checker is what the per-method
split in the GCP file exists to appease (§2.2), so a shape mismatch across operation objects surfaces
here rather than at apply.

Then `terraform plan` against each of these, confirming the expected shape of the rendered document
via `terraform console` (`jsondecode(local.openapi_spec_json).paths`):

| Case | From | Asserts |
| --- | --- | --- |
| Two plain `GET` routes | `examples/aws-containerized/crewai/deploy/main.tf:18-29` | Lowercased method keys, no `parameters`, `uri` ends in the literal `overwrite_path` |
| `ANY` with a path parameter | `examples/aws-containerized/openai-schedule/deploy/main.tf:72-83` | `x-amazon-apigateway-any-method` key; `{task_id}` in the `uri`; one `parameters` entry `in: path`; `requestParameters` maps `integration.request.path.task_id` to `method.request.path.task_id` |
| `ANY` with no path parameter | same example, the `schedules` route | Any-method key, no `parameters`, **no** `options` operation on that path |
| `rest_async` | `queue_mode = true`, `execution_mode = "rest_async"` | The default chat path carries **both** `post` and `get`; exactly one path object for it; the `get` operation's `uri` ends `/api/v1/chat` |
| Non-default base path | `api_base_path = "service"`, `agent_endpoint = "ask"` | The poll route is `GET /service/v1/ask`, **not** `/api/v1/chat`. This is the regression the design calls out (`design.md:110-115`) |
| MCP | `enable_mcp_server = true` | One any-method path at `/api/v1/mcp` with `uri` ending `/mcp/` |
| `enable_cors = false` | — | No `options` operation anywhere |
| WebSocket mode | `execution_mode = "async"` | No REST API, deployment, stage or method settings planned; the WS API and its V1 link unchanged |
| **Existing WebSocket stack with logging on** | an applied `async` + `enable_api_gateway_logs = true` state | Plans **clean** — no replacement of the role, attachment or account resource, and no state move. Acceptance criterion `design.md:284` |
| Throttling off | `throttling_rate_limit = null` | No `aws_api_gateway_method_settings` |
| Timeouts | defaults | Every **routed** operation carries `timeoutInMillis: 900000`; one without it is the 29 s bug (§0). Preflight operations carry neither it nor `responseTransferMode`, by design (§2.4) |

### On a deployed stack

Run `research/aws-claims-to-verify.md`'s claims **first** — they decide whether the rest is worth
measuring. Claim 5 is already settled from the AWS reference and needs no deployment (§0).

1. **Claim 3 — does `STREAM` stream?** Deploy an ECS example whose framework supports token
   streaming, `execution.mode: rest_sync`, `execution.message_type: delta`, with a **Redis or Valkey**
   response store (DynamoDB cannot stream chunks and would fail for an unrelated reason, hiding the
   result). `curl -N -X POST <invoke_url>/api/v1/chat -d '…'`, timestamping arrivals. Chunks spread
   over seconds is a pass; one burst at the end is a fail and is the current HTTP API behaviour. Run
   the same request against the old stack so "it streamed" is not confused with "the reply was short".
2. **Claim 2 — does the REST API reach the ALB with no NLB?** Implied by the stack applying and
   serving one request end to end.
3. **Claim 4a — the real idle timeout.** Drive a request whose agent stays silent for a measured
   interval before replying, and bisect the drop point, with `alb_idle_timeout` set to **900** so the
   ALB is not the thing being measured. The result sets the variable's default.
4. **Claim 4b — the real total limit.** Drive a request that emits a chunk every two seconds and keeps
   going, and record how long the stream survives with `gateway_integration_timeout` at 900, then at
   120. If the 120 run is cut at two minutes, `timeoutInMillis` is honoured under `STREAM` and the
   variable is real; if both runs are cut at the same point, AWS's fixed ceiling wins and the variable
   documents a limit it cannot raise — say so in its description. Confirm which component closed the
   connection (ALB access logs, or the shape of the client error) before attributing the number.

Then the acceptance criteria:

- SSE streams under `rest_sync` + `delta`, and `terraform plan` no longer rejects it.
- `rest_sync`, `rest_async` and MCP all deploy and serve behind the Regional REST API.
- `/chat-multipart` round-trips a file (binary media types), CORS preflight returns the container's
  headers, throttling takes effect, and access logs carry both `resourcePath` and `routeKey`.
- The weekly integration tests and the e2e messaging harness pass. The e2e harness is the real test of
  Behavioural change 1: its webhook URLs are rebuilt from `api_gateway_id` and `api_gateway_stage`
  (`e2e/app/deploy/outputs.tf:2`), so a re-apply re-registers them.

---

## Documentation changes

Per `design.md:287-313`. These assert that ECS queue mode refuses SSE and are now false:

- `ak-py/src/agentkernel/skills/ak-cloud-deploy/SKILL.md:50`, `:860`, `:1161`
- `docs/docs/deployment/aws-containerized.md:18`
- `docs/docs/advanced/queue-mode-guide.md:536`, `:742`
- `ak-deployment/ak-aws/containerized/README.md:411`
- `docs/specs/remove-direct-mode/research/blockers.md:13` (B5), and the #870 design's "SSE on ECS"
  non-goal
- `.agents/skills/ak-dev-architecture/SKILL.md:1553` — the `IOHandler` row. The only dev skill affected

Two are corrections rather than rewordings:

- Containerized `README.md:293` and the notes at `:289-291` state the HTTP API does **not** need the
  account-level CloudWatch role. That becomes false.
- `queue-mode-guide.md:546` (the store-capability table) is **gate 4 and stays**. Where these pages
  describe SSE in the single-container topology, that wording belongs to the direct-mode removal and
  is not edited here.

New material:

- **An "Upgrading" section in `docs/docs/deployment/aws-containerized.md`** naming webhook
  re-registration as a step, and the ALB idle-timeout change.
- **`changelog.d/978.breaking.md`** carries the invoke-URL change (Behavioural change 1). Release
  bodies are compiled from these fragments by towncrier, **not** from PR titles
  (`.github/workflows/publish.yaml:101-102`, `:249-252`), so this fragment is the release note. It
  opens `To migrate, ...` per the house rule and names webhook re-registration.
  `changelog.d/870.breaking.md` is the shape to follow: same ECS surface, same migration sentence.
  - A second fragment, **`changelog.d/978.added.md`**, records SSE becoming available in ECS queue
    mode. One fragment per user-visible change, so the two do not merge.
  - Both belong to the **implementation** PR, not to the spec PRs. A `docs:`-titled PR needs no
    fragment, and one merged ahead of the code would compile into a release that does not contain it.
  - Fragment prose takes **no em or en dashes** (`changelog.d/README.md`, CONTRIBUTING's "Changelog
    entries"), unlike these spec documents.
- `docs/docs/whats-new.md` gets the capability entry. It is not a migration surface.
- `alb_idle_timeout`, `gateway_integration_timeout` and the two new outputs in the containerized
  `README.md` variable and output tables. The two timeouts are documented **together**, since the
  common mistake will be raising one and expecting it to extend a stream the other is cutting.

Not revived: `README.md:684` points at three migration files that do not exist. Pre-existing, out of
scope.

---

## Discovered while detailing

Four things this pass turned up that `design.md` did not cover. None blocks implementation; each needs
a reviewer's call. The first is the material one.

0. **The integration timeout is a second cap, and omitting it caps SSE at 29 s** (§0). This adds a
   requirement, a variable (`gateway_integration_timeout`) and a measurement (claim 4b), and it makes
   the `alb_idle_timeout` default provisional too — the 5-minute figure it was chosen to match
   describes total duration, not idle time. `design.md` and the research file are updated.
1. **`gateway_endpoints_map.path` must be normalised** (§1.1), which contradicts `design.md:82-83`.
   Safe — nothing reads the field — but the design sentence needs correcting.
2. **Declaring external path-template parameters is mandatory**, separately from translating
   `overwrite_path` expressions (§2.1, `templated`). The design describes only the second half. Without
   the first, the `ANY /api/v1/schedules/{task_id}` example does not import.
3. **A plan-time `check` for a path expression with no matching path template** would catch
   Behavioural change 6 before apply rather than during it — one more named check beside §7.3's.
   Deliberately **not** specified: it is new scope, and apply-time rejection is already a large
   improvement on today's silent 404. Raise it as a follow-up if wanted.

Two adjacent problems were confirmed as out of scope and already filed: serverless silently truncates
paths beyond three segments (#1007), and the container's CORS policy is not configurable (#1006). The
GCP modules paste `overwrite_path` into a literal backend URL and would forward a `$request.*`
expression as text (`ak-gcp/containerized/api_gateway.tf:54`) — latent, since no GCP example uses one,
and a non-goal here.
