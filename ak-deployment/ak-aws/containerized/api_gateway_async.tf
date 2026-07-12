# ---------- API Gateway Async Mode Integration ----------
# Only needed for rest_async mode — adds GET /api/{version}/{endpoint} for polling.
#
# The client polls by request_id, passed as a query string (e.g. ?request_id=<uuid>). The
# backend AWSRestHandler.poll_response reads request_id (and optional session_id) from the
# query string on GET /api/v1/chat — the SAME path as the enqueue POST, just a different
# method (see deployment/common/rest_handler.py). API Gateway forwards the query string
# unchanged, so only the path is rewritten here.

resource "aws_apigatewayv2_integration" "async_get" {
  count                = var.queue_mode && var.execution_mode == "rest_async" ? 1 : 0
  api_id               = aws_apigatewayv2_api.http_api.id
  integration_type     = "HTTP_PROXY"
  integration_method   = "ANY"
  integration_uri      = module.rest_service.alb_listener_arn
  connection_type      = "VPC_LINK"
  connection_id        = aws_apigatewayv2_vpc_link.ecs_alb.id
  passthrough_behavior = "WHEN_NO_MATCH"

  request_parameters = {
    "overwrite:path" = "/api/v1/chat"
  }
}

resource "aws_apigatewayv2_route" "async_get" {
  count     = var.queue_mode && var.execution_mode == "rest_async" ? 1 : 0
  api_id    = aws_apigatewayv2_api.http_api.id
  route_key = "GET ${local.api_base_segment_with_version}/${var.agent_endpoint}"
  target    = "integrations/${aws_apigatewayv2_integration.async_get[0].id}"
}
