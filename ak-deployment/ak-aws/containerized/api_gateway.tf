resource "aws_apigatewayv2_api" "http_api" {
  count         = local.is_websocket_mode ? 0 : 1
  name          = "${var.product_alias}-${var.env_alias}-http-api-${var.region}"
  protocol_type = "HTTP"
  description   = "[${var.env_alias}] ${var.product_display_name} HTTP API"
  tags          = var.tags

  dynamic "cors_configuration" {
    for_each = var.enable_cors ? [1] : []
    content {
      allow_credentials = var.cors_allow_credentials
      allow_headers     = var.cors_allow_headers
      allow_methods     = var.cors_allow_methods
      allow_origins     = var.cors_allow_origins
      expose_headers    = var.cors_expose_headers
      max_age           = var.cors_max_age
    }
  }
}

resource "aws_apigatewayv2_vpc_link" "ecs_alb" {
  count              = local.is_websocket_mode ? 0 : 1
  name               = "${var.product_alias}-${var.env_alias}-httpapi-vpclink"
  security_group_ids = [module.rest_service.alb_security_group_id]
  subnet_ids         = local.subnet_ids
  tags               = var.tags
}

resource "aws_apigatewayv2_integration" "alb_proxy" {
  for_each             = local.is_websocket_mode ? {} : local.gateway_endpoints_map
  api_id               = aws_apigatewayv2_api.http_api[0].id
  integration_type     = "HTTP_PROXY"
  integration_method   = "ANY"
  integration_uri      = module.rest_service.alb_listener_arn
  connection_type      = "VPC_LINK"
  connection_id        = aws_apigatewayv2_vpc_link.ecs_alb[0].id
  passthrough_behavior = "WHEN_NO_MATCH"
  request_parameters = try(each.value["overwrite_path"], null) != null ? {
    "overwrite:path" = each.value["overwrite_path"]
  } : {}
}

resource "aws_apigatewayv2_route" "gateway_routes" {
  for_each  = local.is_websocket_mode ? {} : local.gateway_endpoints_map
  api_id    = aws_apigatewayv2_api.http_api[0].id
  route_key = each.key
  target    = "integrations/${aws_apigatewayv2_integration.alb_proxy[each.key].id}"
}

# CloudWatch Log Group for API Gateway (only when access logging is enabled)
resource "aws_cloudwatch_log_group" "http_api" {
  count             = var.enable_api_gateway_logs && !local.is_websocket_mode ? 1 : 0
  name              = "/aws/apigateway/${var.product_alias}-${var.env_alias}-http-api"
  retention_in_days = 90
  tags              = var.tags
}

resource "aws_apigatewayv2_stage" "stage" {
  count       = local.is_websocket_mode ? 0 : 1
  api_id      = aws_apigatewayv2_api.http_api[0].id
  name        = "agents"
  auto_deploy = true

  dynamic "default_route_settings" {
    for_each = var.throttling_rate_limit != null && var.throttling_burst_limit != null ? [1] : []
    content {
      throttling_rate_limit  = var.throttling_rate_limit
      throttling_burst_limit = var.throttling_burst_limit
    }
  }

  dynamic "access_log_settings" {
    for_each = var.enable_api_gateway_logs ? [1] : []
    content {
      destination_arn = aws_cloudwatch_log_group.http_api[0].arn
      format = jsonencode({
        requestId               = "$context.requestId",
        sourceIp                = "$context.identity.sourceIp",
        requestTime             = "$context.requestTime",
        protocol                = "$context.protocol",
        httpMethod              = "$context.httpMethod",
        routeKey                = "$context.routeKey",
        status                  = "$context.status",
        responseLength          = "$context.responseLength",
        integrationErrorMessage = "$context.integrationErrorMessage"
      })
    }
  }
}
