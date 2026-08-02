# API Gateway Async Mode Integration
# rest_async only: adds GET /api/v1/chat (polls with request_id in the JSON body, not a query
# string — see RestHandler.poll_response); only the path is rewritten, the body passes through.

resource "aws_apigatewayv2_integration" "async_get" {
  count                = var.queue_mode && var.execution_mode == "rest_async" ? 1 : 0
  api_id               = aws_apigatewayv2_api.http_api[0].id
  integration_type     = "HTTP_PROXY"
  integration_method   = "ANY"
  integration_uri      = module.rest_service.alb_listener_arn
  connection_type      = "VPC_LINK"
  connection_id        = aws_apigatewayv2_vpc_link.ecs_alb[0].id
  passthrough_behavior = "WHEN_NO_MATCH"

  request_parameters = {
    "overwrite:path" = "/api/v1/chat"
  }
}

resource "aws_apigatewayv2_route" "async_get" {
  count     = var.queue_mode && var.execution_mode == "rest_async" ? 1 : 0
  api_id    = aws_apigatewayv2_api.http_api[0].id
  route_key = "GET ${local.api_base_segment_with_version}/${var.agent_endpoint}"
  target    = "integrations/${aws_apigatewayv2_integration.async_get[0].id}"
}
