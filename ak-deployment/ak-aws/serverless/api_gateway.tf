resource "aws_api_gateway_rest_api" "rest_api" {
  name        = "${var.product_alias}-${var.env_alias}-rest-api-${var.region}"
  description = "[${var.env_alias}] ${var.product_display_name} REST API"
  endpoint_configuration { types = ["REGIONAL"] }
  tags        = var.tags
}

resource "aws_api_gateway_resource" "api" {
  rest_api_id = aws_api_gateway_rest_api.rest_api.id
  parent_id   = aws_api_gateway_rest_api.rest_api.root_resource_id
  path_part   = var.api_base_path
}

resource "aws_api_gateway_resource" "version" {
  rest_api_id = aws_api_gateway_rest_api.rest_api.id
  parent_id   = aws_api_gateway_resource.api.id
  path_part   = var.api_version
}

resource "aws_api_gateway_resource" "main" {
  for_each = local.mainpaths
  rest_api_id = aws_api_gateway_rest_api.rest_api.id
  parent_id   = aws_api_gateway_resource.version.id
  path_part   = each.key
}

resource "aws_api_gateway_resource" "sub" {
  for_each    = local.sub_resources
  rest_api_id = aws_api_gateway_rest_api.rest_api.id
  parent_id   = aws_api_gateway_resource.main[each.value[0].mainpath].id
  path_part   = each.value[0].subpath
}

resource "aws_api_gateway_resource" "child" {
  for_each = local.child_resources
  rest_api_id = aws_api_gateway_rest_api.rest_api.id
  parent_id   = aws_api_gateway_resource.sub["${each.value[0].mainpath}/${each.value[0].subpath}"].id
  path_part = each.value[0].childpath
}

resource "aws_api_gateway_method" "endpoint" {
  for_each = local.all_endpoints
  rest_api_id = aws_api_gateway_rest_api.rest_api.id
  resource_id = (
    each.value.childpath != "" ?
      aws_api_gateway_resource.child[
        "${each.value.mainpath}/${each.value.subpath}/${each.value.childpath}"
      ].id :
    each.value.subpath != "" ?
      aws_api_gateway_resource.sub[
        "${each.value.mainpath}/${each.value.subpath}"
      ].id :
      aws_api_gateway_resource.main[each.value.mainpath].id
  )
  http_method  = each.value.method
  authorization = local.create_authorizer ? "CUSTOM" : "NONE"
  authorizer_id = local.create_authorizer ? aws_api_gateway_authorizer.lambda_authorizer[0].id : null
}

resource "aws_api_gateway_integration" "endpoint" {
  for_each                = local.all_endpoints
  rest_api_id             = aws_api_gateway_rest_api.rest_api.id
  resource_id = (
    each.value.childpath != "" ?
      aws_api_gateway_resource.child[
        "${each.value.mainpath}/${each.value.subpath}/${each.value.childpath}"
      ].id :
    each.value.subpath != "" ?
      aws_api_gateway_resource.sub[
        "${each.value.mainpath}/${each.value.subpath}"
      ].id :
      aws_api_gateway_resource.main[each.value.mainpath].id
  )
  http_method             = aws_api_gateway_method.endpoint[each.key].http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = module.lambda_deployment.lambda_function_invoke_arn
}

resource "aws_lambda_permission" "endpoint" {
  action        = "lambda:InvokeFunction"
  function_name = module.lambda_deployment.lambda_function_name
  principal     = "apigateway.amazonaws.com"
  source_arn = "${aws_api_gateway_rest_api.rest_api.execution_arn}/*/*"
}

resource "aws_api_gateway_deployment" "deployment" {
  rest_api_id = aws_api_gateway_rest_api.rest_api.id
  triggers = {
    redeployment = sha1(jsonencode([
      values(aws_api_gateway_resource.main)[*].id,
      values(aws_api_gateway_resource.sub)[*].id,
      values(aws_api_gateway_resource.child)[*].id,
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

  variables = {
    api_base_path  = var.api_base_path
    api_version    = var.api_version
    agent_endpoint = var.agent_endpoint
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

resource "aws_api_gateway_gateway_response" "unauthorized" {
  rest_api_id = aws_api_gateway_rest_api.rest_api.id
  response_type = "UNAUTHORIZED"

  status_code = "401"

  response_templates = {
    "application/json" = jsonencode({
      message = "Authentication failed: invalid or missing credentials."
    })
  }
}

resource "aws_api_gateway_gateway_response" "access_denied" {
  rest_api_id = aws_api_gateway_rest_api.rest_api.id
  response_type = "ACCESS_DENIED"

  status_code = "403"

  response_templates = {
    "application/json" = jsonencode({
      message = "Authentication failed: access denied."
    })
  }
}

resource "aws_lambda_permission" "allow_apigw_authorizer" {
  count       = local.create_authorizer ? 1 : 0
  statement_id = "AllowAPIGatewayInvokeAuthorizer"
  action      = "lambda:InvokeFunction"
  function_name = module.authorizer[0].lambda_function_name
  principal   = "apigateway.amazonaws.com"

  # REST API
  source_arn = "${aws_api_gateway_rest_api.rest_api.execution_arn}/authorizers/*"
}

resource "aws_api_gateway_authorizer" "lambda_authorizer" {
  count    = local.create_authorizer ? 1 : 0
  name     = "${var.product_alias}-${var.env_alias}-${var.authorizer.module_name}-${var.authorizer.function_name}"
  rest_api_id = aws_api_gateway_rest_api.rest_api.id
  authorizer_uri = module.authorizer[0].lambda_function_invoke_arn

  type = "REQUEST"
  identity_source = "method.request.header.Authorization,context.resourcePath"
  authorizer_result_ttl_in_seconds = var.authorizer.result_ttl_in_seconds
}

