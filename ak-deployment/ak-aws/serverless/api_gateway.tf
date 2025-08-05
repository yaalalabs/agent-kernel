resource "aws_api_gateway_rest_api" "rest_api" {

  name        = "${var.product_alias}-${var.env_alias}-rest-api-${var.region}"
  description = "[${var.env_alias}] ${var.product_display_name} REST API"

  endpoint_configuration {
    types = ["REGIONAL"]
  }
  tags = var.tags
}

resource "aws_api_gateway_resource" "api" {

  rest_api_id = aws_api_gateway_rest_api.rest_api.id
  parent_id   = aws_api_gateway_rest_api.rest_api.root_resource_id
  path_part   = "api"
}

resource "aws_api_gateway_resource" "version" {

  rest_api_id = aws_api_gateway_rest_api.rest_api.id
  parent_id   = aws_api_gateway_resource.api.id
  path_part   = var.api_version
}

resource "aws_api_gateway_resource" "agent_endpoint" {

  rest_api_id = aws_api_gateway_rest_api.rest_api.id
  parent_id   = aws_api_gateway_resource.version.id
  path_part   = var.agent_endpoint
}
