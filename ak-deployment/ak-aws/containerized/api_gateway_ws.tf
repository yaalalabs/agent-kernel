# WebSocket API Gateway (async / stream) — proxies frames to the REST service via VPC Link + ALB.

locals {
  ws_stage_name = "agents"

  # All WebSocket route keys: predefined + configurable chat route + custom routes.
  ws_routes_all = local.is_websocket_mode ? toset(concat(
    ["$connect", "$disconnect", "$default", var.ws_chat_route],
    [for r in var.ws_routes : r.route]
  )) : toset([])

  # Backend path per WebSocket route. The ECS service exposes ONE endpoint per route
  # (see ECSWebSocketRequestHandler) instead of dispatching internally, so each route
  # rewrites the request path to its dedicated container endpoint. Predefined routes use
  # fixed paths; the chat route and any custom routes map to /ws/<route-name>.
  ws_route_backend_paths = local.is_websocket_mode ? merge(
    {
      "$connect"          = "/ws/connect"
      "$disconnect"       = "/ws/disconnect"
      "$default"          = "/ws/default"
      (var.ws_chat_route) = "/ws/chat"
    },
    { for r in var.ws_routes : r.route => "/ws/${r.route}" }
  ) : {}
}

resource "aws_apigatewayv2_api" "ws_api" {
  count                      = local.is_websocket_mode ? 1 : 0
  name                       = "${var.product_alias}-${var.env_alias}-ws-api-${var.region}"
  protocol_type              = "WEBSOCKET"
  route_selection_expression = "$request.body.route"
  description                = "[${var.env_alias}] ${var.product_display_name} WebSocket API"
  tags                       = var.tags
}

# WebSocket private integrations require VPC Link V1 (NLB-backed); V2 is HTTP-API-only.
resource "aws_api_gateway_vpc_link" "ws" {
  count       = local.is_websocket_mode ? 1 : 0
  name        = "${var.product_alias}-${var.env_alias}-ws-vpclink"
  target_arns = [module.rest_service.nlb_arn]
  tags        = var.tags
}

resource "aws_apigatewayv2_integration" "ws" {
  for_each = local.ws_routes_all

  api_id               = aws_apigatewayv2_api.ws_api[0].id
  integration_type     = "HTTP_PROXY"
  integration_method   = "POST"
  integration_uri      = module.rest_service.nlb_listener_arn
  connection_type      = "VPC_LINK"
  connection_id        = aws_api_gateway_vpc_link.ws[0].id
  passthrough_behavior = "WHEN_NO_MATCH"

  # Route each WS route to its dedicated container endpoint (overwrite:path) and pass the
  # $context the app needs to identify the connection and push replies back over it.
  # NOTE: overwrite:* is parameter-mapping syntax; validate it is accepted for this WebSocket
  # API in your account/region. If not, the fallback is classic header mapping
  # ("integration.request.header.x-ws-route" = "context.routeKey") plus in-app dispatch.
  request_parameters = merge(
    {
      "overwrite:header.x-ws-connection-id" = "$context.connectionId"
      "overwrite:header.x-ws-domain-name"   = "$context.domainName"
      "overwrite:header.x-ws-stage"         = "$context.stage"
    },
    {
      "overwrite:path" = local.ws_route_backend_paths[each.value]
    }
  )
}

resource "aws_apigatewayv2_route" "ws" {
  for_each = local.ws_routes_all

  api_id    = aws_apigatewayv2_api.ws_api[0].id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.ws[each.value].id}"
}

resource "aws_cloudwatch_log_group" "ws_api" {
  count             = local.is_websocket_mode ? 1 : 0
  name              = "/aws/apigateway/${var.product_alias}-${var.env_alias}-ws-api"
  retention_in_days = 90
  tags              = var.tags
}

# WebSocket access logging requires an account-level CloudWatch Logs role (region-wide singleton); else CreateStage fails.
resource "aws_iam_role" "apigw_cloudwatch" {
  count = local.is_websocket_mode ? 1 : 0
  name  = "${var.product_alias}-${var.env_alias}-apigw-cw-role-${var.region}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "apigateway.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "apigw_cloudwatch" {
  count      = local.is_websocket_mode ? 1 : 0
  role       = aws_iam_role.apigw_cloudwatch[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonAPIGatewayPushToCloudWatchLogs"
}

resource "aws_api_gateway_account" "this" {
  count               = local.is_websocket_mode ? 1 : 0
  cloudwatch_role_arn = aws_iam_role.apigw_cloudwatch[0].arn

  depends_on = [aws_iam_role_policy_attachment.apigw_cloudwatch]
}

resource "aws_apigatewayv2_stage" "ws" {
  count       = local.is_websocket_mode ? 1 : 0
  api_id      = aws_apigatewayv2_api.ws_api[0].id
  name        = local.ws_stage_name
  auto_deploy = true

  # The account-level CloudWatch role must exist before the stage enables access logging.
  depends_on = [aws_api_gateway_account.this]

  dynamic "default_route_settings" {
    for_each = var.throttling_rate_limit != null && var.throttling_burst_limit != null ? [1] : []
    content {
      throttling_rate_limit  = var.throttling_rate_limit
      throttling_burst_limit = var.throttling_burst_limit
    }
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.ws_api[0].arn
    format = jsonencode({
      requestId               = "$context.requestId"
      sourceIp                = "$context.identity.sourceIp"
      requestTime             = "$context.requestTime"
      protocol                = "$context.protocol"
      routeKey                = "$context.routeKey"
      status                  = "$context.status"
      responseLength          = "$context.responseLength"
      connectionId            = "$context.connectionId"
      integrationErrorMessage = "$context.integrationErrorMessage"
    })
  }

  tags = var.tags
}
