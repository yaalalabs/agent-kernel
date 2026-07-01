# ---------- API Gateway Async Mode Integration ----------
# Only needed for rest_async mode — adds GET /api/{version}/{endpoint}/{sessionId}

resource "aws_apigatewayv2_integration" "async_get" {
  count                = var.enable_queue_mode && var.queue_mode_type == "async" ? 1 : 0
  api_id               = aws_apigatewayv2_api.http_api.id
  integration_type     = "HTTP_PROXY"
  integration_method   = "ANY"
  integration_uri      = module.rest_service.alb_listener_arn
  connection_type      = "VPC_LINK"
  connection_id        = aws_apigatewayv2_vpc_link.ecs_alb.id
  passthrough_behavior = "WHEN_NO_MATCH"

  request_parameters = {
    "overwrite:path" = "/api/v1/chat/$request.path.sessionId"
  }
}

resource "aws_apigatewayv2_route" "async_get" {
  count     = var.enable_queue_mode && var.queue_mode_type == "async" ? 1 : 0
  api_id    = aws_apigatewayv2_api.http_api.id
  route_key = "GET ${local.api_base_segment_with_version}/${var.agent_endpoint}/{sessionId}"
  target    = "integrations/${aws_apigatewayv2_integration.async_get[0].id}"
}
