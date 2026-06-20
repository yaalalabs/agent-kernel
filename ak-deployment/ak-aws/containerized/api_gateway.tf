resource "aws_apigatewayv2_api" "http_api" {
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
  name               = "${var.product_alias}-${var.env_alias}-httpapi-vpclink"
  security_group_ids = [module.rest_service.alb_security_group_id]
  subnet_ids         = local.subnet_ids
  tags               = var.tags
}

resource "aws_apigatewayv2_integration" "alb_proxy" {
  for_each             = local.gateway_endpoints_map
  api_id               = aws_apigatewayv2_api.http_api.id
  integration_type     = "HTTP_PROXY"
  integration_method   = "ANY"
  integration_uri      = module.rest_service.alb_listener_arn
  connection_type      = "VPC_LINK"
  connection_id        = aws_apigatewayv2_vpc_link.ecs_alb.id
  passthrough_behavior = "WHEN_NO_MATCH"
  request_parameters = try(each.value["overwrite_path"], null) != null ? {
    "overwrite:path" = each.value["overwrite_path"]
  } : {}
}

resource "aws_apigatewayv2_route" "gateway_routes" {
  for_each  = local.gateway_endpoints_map
  api_id    = aws_apigatewayv2_api.http_api.id
  route_key = each.key
  target    = "integrations/${aws_apigatewayv2_integration.alb_proxy[each.key].id}"
}

resource "aws_cloudwatch_log_group" "http_api" {
  name              = "/aws/apigateway/${var.product_alias}-${var.env_alias}-http-api"
  retention_in_days = 90
}

resource "aws_apigatewayv2_stage" "stage" {
  api_id      = aws_apigatewayv2_api.http_api.id
  name        = "agents"
  auto_deploy = true

  dynamic "default_route_settings" {
    for_each = var.throttling_rate_limit != null && var.throttling_burst_limit != null ? [1] : []
    content {
      throttling_rate_limit  = var.throttling_rate_limit
      throttling_burst_limit = var.throttling_burst_limit
    }
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.http_api.arn
    format = jsonencode({
      requestId      = "$context.requestId",
      sourceIp       = "$context.identity.sourceIp",
      requestTime    = "$context.requestTime",
      protocol       = "$context.protocol",
      httpMethod     = "$context.httpMethod",
      routeKey       = "$context.routeKey",
      status         = "$context.status",
      responseLength = "$context.responseLength"
    })
  }
}