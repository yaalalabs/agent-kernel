locals {
  # $request.path.x, braced or not. The HTTP API also accepted header and querystring sources in
  # overwrite:path; the REST API resolves a reference only by mapping it onto an integration path
  # parameter, so gateway_endpoints rejects those forms rather than mistranslating them
  # (variables.tf). Terraform's regex engine is RE2, so with no lookarounds the name's character
  # class carries the right-hand boundary.
  _param_re = "\\$\\{?request\\.path\\.([A-Za-z0-9_-]+)\\}?"

  _eps = {
    for key, ep in local.rest_endpoints_map :
    key => {
      ext_path = ep.path
      method   = lower(try(ep.method, "ANY"))
      is_any   = lower(try(ep.method, "ANY")) == "any"

      # distinct(): one overwrite_path may reference the same parameter twice, which would make
      # duplicate keys below.
      mapped = distinct([for m in regexall(local._param_re, try(ep.overwrite_path, "")) : m[0]])

      # API Gateway rejects an import whose path template declares {x} that the operation does not
      # list in `parameters`, so these are required whether or not overwrite_path references them.
      templated = [for m in regexall("\\{([A-Za-z0-9_-]+)\\+?\\}", ep.path) : m[0]]

      backend_path = replace(try(ep.overwrite_path, ""), "/${local._param_re}/", "{$1}")
    }
  }

  # Only `templated` is enumerated: gateway_endpoints requires every $request.path.<name> to name a
  # parameter the external path already declares, so `mapped` is always a subset of it.
  _ep_params = {
    for key, ep in local._eps :
    key => [for n in ep.templated : {
      name     = n
      in       = "path"
      required = true
      schema   = { type = "string" }
    }]
  }

  _ep_request_params = {
    for key, ep in local._eps :
    key => {
      for n in ep.mapped :
      "integration.request.path.${n}" => "method.request.path.${n}"
    }
  }

  _ep_operations = {
    for key, ep in local._eps :
    key => {
      summary     = "Route to ${ep.ext_path}"
      operationId = "${replace(ep.method, "any", "any-method")}-${replace(trim(ep.ext_path, "/"), "/", "-")}"
      parameters  = local._ep_params[key]
      responses   = { "200" = { description = "Success" } }
      "x-amazon-apigateway-integration" = {
        type       = "http_proxy"
        httpMethod = "ANY"
        # The integration's own method: forward whatever the caller used. Unrelated to the
        # operation's key, and required even on a single-method operation.
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

  _method_key = {
    for key, ep in local._eps :
    key => ep.is_any ? "x-amazon-apigateway-any-method" : ep.method
  }

  # An ANY operation already accepts OPTIONS, so only paths without one need a preflight. Proxied to
  # the container rather than mocked, because CORSMiddleware already answers preflight there.
  _non_any_keys_by_path = {
    for key, ep in local._eps : ep.ext_path => key... if !ep.is_any
  }

  _options_op = {
    for path, ep_keys in local._non_any_keys_by_path :
    path => {
      summary     = "CORS pre-flight for ${path}"
      operationId = "options-${replace(trim(path, "/"), "/", "-")}"
      parameters  = [for n in local._eps[ep_keys[0]].templated : { name = n, in = "path", required = true, schema = { type = "string" } }]
      responses   = { "200" = { description = "CORS pre-flight" } }
      "x-amazon-apigateway-integration" = {
        type       = "http_proxy"
        httpMethod = "OPTIONS"
        # Neither responseTransferMode nor timeoutInMillis: a preflight response is a few headers,
        # with nothing to stream and well inside the 29 s default.
        connectionType      = "VPC_LINK"
        connectionId        = one(aws_apigatewayv2_vpc_link.ecs_alb[*].id)
        integrationTarget   = module.rest_service.alb_arn
        uri                 = "http://${module.rest_service.alb_dns_name}${local._eps[ep_keys[0]].backend_path}"
        passthroughBehavior = "when_no_match"
        requestParameters   = local._ep_request_params[ep_keys[0]]
      }
    }
    if var.enable_cors
  }

  # One path object per external path, carrying every method served on it: the rest_async poll route
  # shares the default chat path with the POST.
  openapi_paths_block = {
    for path in distinct([for ep in values(local._eps) : ep.ext_path]) :
    path => merge(concat(
      [for key, ep in local._eps : { (local._method_key[key]) = local._ep_operations[key] } if ep.ext_path == path],
      [for p, op in local._options_op : { options = op } if p == path],
    )...)
  }

  openapi_spec = {
    openapi = "3.0.1"
    info = {
      title       = "${var.product_display_name} API"
      description = "[${var.prefix}] ${var.product_display_name} REST API"
      version     = var.api_version
    }
    paths = local.openapi_paths_block
    # /chat-multipart bodies are corrupted silently without this.
    "x-amazon-apigateway-binary-media-types" = ["multipart/form-data"]
  }

  openapi_spec_json = jsonencode(local.openapi_spec)
}

resource "aws_apigatewayv2_vpc_link" "ecs_alb" {
  count              = local.is_websocket_mode ? 0 : 1
  name               = "${var.prefix}-httpapi-vpclink"
  security_group_ids = [module.rest_service.alb_security_group_id]
  subnet_ids         = local.subnet_ids
  tags               = var.tags
}

resource "aws_api_gateway_rest_api" "rest_api" {
  count       = local.is_websocket_mode ? 0 : 1
  name        = "${var.prefix}-rest-api-${var.region}"
  description = "[${var.prefix}] ${var.product_display_name} REST API"
  body        = local.openapi_spec_json

  # The body is the whole definition; "overwrite" makes an apply converge on it rather than merging
  # into whatever the last one left behind.
  put_rest_api_mode = "overwrite"

  endpoint_configuration {
    # REGIONAL, not EDGE: an edge-optimized endpoint keeps a 30 s streaming idle cap.
    types = ["REGIONAL"]
  }

  tags = var.tags
}

# The Terraform address moves; the AWS log group name keeps its -http-api string, because renaming it
# would destroy the group and its retained access logs.
moved {
  from = aws_cloudwatch_log_group.http_api
  to   = aws_cloudwatch_log_group.rest_api
}

resource "aws_cloudwatch_log_group" "rest_api" {
  count             = var.enable_api_gateway_logs && !local.is_websocket_mode ? 1 : 0
  name              = "/aws/apigateway/${var.prefix}-http-api"
  retention_in_days = 90
  tags              = var.tags
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

# A REST stage carries no inline throttle block; this is what default_route_settings expressed on the
# v2 stage. "*/*" is the all-methods-all-resources wildcard, matching that block's scope.
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
