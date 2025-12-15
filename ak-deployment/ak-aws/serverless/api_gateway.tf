resource "aws_api_gateway_rest_api" "rest_api" {
  name        = "${var.product_alias}-${var.env_alias}-rest-api-${var.region}"
  description = "[${var.env_alias}] ${var.product_display_name} REST API"
  endpoint_configuration { types = ["REGIONAL"] }
  tags        = var.tags
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

resource "aws_api_gateway_resource" "endpoint" {
  for_each   = local.all_endpoints
  rest_api_id = aws_api_gateway_rest_api.rest_api.id
  parent_id   = aws_api_gateway_resource.version.id
  path_part   = each.value.path
}

resource "aws_api_gateway_method" "endpoint" {
  for_each     = local.all_endpoints
  rest_api_id  = aws_api_gateway_rest_api.rest_api.id
  resource_id  = aws_api_gateway_resource.endpoint[each.key].id
  http_method  = each.value.method
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "endpoint" {
  for_each                = local.all_endpoints
  rest_api_id             = aws_api_gateway_rest_api.rest_api.id
  resource_id             = aws_api_gateway_resource.endpoint[each.key].id
  http_method             = aws_api_gateway_method.endpoint[each.key].http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = module.lambda_deployment.lambda_function_invoke_arn
}

resource "aws_lambda_permission" "endpoint" {
  for_each = local.all_endpoints

  statement_id  = "AllowAPIGatewayInvoke-${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = module.lambda_deployment.lambda_function_name
  principal     = "apigateway.amazonaws.com"
  source_arn = "${aws_api_gateway_rest_api.rest_api.execution_arn}/*/*/api/${var.api_version}/${each.value.path}"
}

resource "aws_api_gateway_deployment" "deployment" {
  rest_api_id = aws_api_gateway_rest_api.rest_api.id
  triggers = {
    redeployment = sha1(jsonencode([
      values(aws_api_gateway_resource.endpoint)[*].id,
      values(aws_api_gateway_method.endpoint)[*].id,
      values(aws_api_gateway_integration.endpoint)[*].id
    ]))
  }
  lifecycle {
    create_before_destroy = true
  }
  depends_on = [
    aws_api_gateway_integration.endpoint
  ]
}

resource "aws_cloudwatch_log_group" "api_gateway" {
  name              = "/aws/api-gateway/${var.product_alias}-${var.env_alias}-rest-api"
  retention_in_days = 90
}

resource "aws_iam_role" "cloudwatch" {
  name = "${var.product_alias}-${var.env_alias}-api-gateway-cloudwatch-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "apigateway.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "cloudwatch" {
  name = "${var.product_alias}-${var.env_alias}-api-gateway-cloudwatch-policy"
  role = aws_iam_role.cloudwatch.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams",
          "logs:PutLogEvents",
          "logs:GetLogEvents",
          "logs:FilterLogEvents"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_api_gateway_account" "api_gateway" {
  cloudwatch_role_arn = aws_iam_role.cloudwatch.arn
}

resource "aws_api_gateway_stage" "stage" {
  deployment_id = aws_api_gateway_deployment.deployment.id
  rest_api_id   = aws_api_gateway_rest_api.rest_api.id
  stage_name    = "agents"
  lifecycle {
    ignore_changes = [deployment_id]
  }
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gateway.arn
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
    }
    )
  }

  depends_on = [aws_api_gateway_account.api_gateway]
}