# WebSocket API Gateway (async / stream) — proxies frames to the REST service via VPC Link + ALB.

locals {
  ws_stage_name = "agents"

  # All WebSocket route keys: predefined + configurable chat route + custom routes.
  ws_routes_all = local.is_websocket_mode ? toset(concat(
    ["$connect", "$disconnect", "$default", var.ws_chat_route],
    [for r in var.ws_routes : r.route]
  )) : toset([])
}

resource "aws_apigatewayv2_api" "ws_api" {
  count                      = local.is_websocket_mode ? 1 : 0
  name                       = "${var.product_alias}-${var.env_alias}-ws-api-${var.region}"
  protocol_type              = "WEBSOCKET"
  route_selection_expression = "$request.body.route"
  description                = "[${var.env_alias}] ${var.product_display_name} WebSocket API"
  tags                       = var.tags
}

resource "aws_apigatewayv2_integration" "ws" {
  for_each = local.ws_routes_all

  api_id               = aws_apigatewayv2_api.ws_api[0].id
  integration_type     = "HTTP_PROXY"
  integration_method   = "POST"
  integration_uri      = module.rest_service.alb_listener_arn
  connection_type      = "VPC_LINK"
  connection_id        = aws_apigatewayv2_vpc_link.ecs_alb.id
  passthrough_behavior = "WHEN_NO_MATCH"

  # Map WebSocket $context into headers so the app can dispatch and push replies.
  request_parameters = {
    "integration.request.header.x-ws-route"         = "context.routeKey"
    "integration.request.header.x-ws-connection-id" = "context.connectionId"
    "integration.request.header.x-ws-event-type"    = "context.eventType"
    "integration.request.header.x-ws-domain-name"   = "context.domainName"
    "integration.request.header.x-ws-stage"         = "context.stage"
  }
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

resource "aws_apigatewayv2_stage" "ws" {
  count       = local.is_websocket_mode ? 1 : 0
  api_id      = aws_apigatewayv2_api.ws_api[0].id
  name        = local.ws_stage_name
  auto_deploy = true

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
