resource "aws_apigatewayv2_api" "http_api" {
  name          = "${var.product_alias}-${var.env_alias}-http-api-${var.region}"
  protocol_type = "HTTP"
  description   = "[${var.env_alias}] ${var.product_display_name} HTTP API"
  tags          = var.tags
}

resource "aws_apigatewayv2_vpc_link" "ecs_alb" {
  name               = "${var.product_alias}-${var.env_alias}-httpapi-vpclink"
  security_group_ids = [aws_security_group.ecs_alb.id]
  subnet_ids         = local.subnet_ids
  tags               = var.tags
}

resource "aws_apigatewayv2_integration" "alb_proxy" {
  api_id                 = aws_apigatewayv2_api.http_api.id
  integration_type       = "HTTP_PROXY"
  integration_method     = "ANY"
  integration_uri        = aws_lb_listener.http.arn
  connection_type        = "VPC_LINK"
  connection_id          = aws_apigatewayv2_vpc_link.ecs_alb.id
  passthrough_behavior   = "WHEN_NO_MATCH"

  # Ensure the backend receives the path expected by the app
  request_parameters = {
    "overwrite:path" = "/run"
  }
}

resource "aws_apigatewayv2_route" "post_agent" {
  api_id    = aws_apigatewayv2_api.http_api.id
  route_key = "POST /api/${var.api_version}/${var.agent_endpoint}"
  target    = "integrations/${aws_apigatewayv2_integration.alb_proxy.id}"
}

resource "aws_cloudwatch_log_group" "http_api" {
  name              = "/aws/apigateway/${var.product_alias}-${var.env_alias}-http-api"
  retention_in_days = 90
}

resource "aws_apigatewayv2_stage" "stage" {
  api_id      = aws_apigatewayv2_api.http_api.id
  name        = "agents"
  auto_deploy = true

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