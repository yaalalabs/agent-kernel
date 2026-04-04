# Locals for endpoint processing
locals {
  normalized_endpoints = [
    for ep in var.endpoints : {
      parts  = split("/", trim(ep.path, "/"))
      method = ep.method
    }
  ]
  converted_endpoints = [
    for ep in local.normalized_endpoints : {
      mainpath  = ep.parts[0]
      subpath   = length(ep.parts) > 1 ? ep.parts[1] : ""
      childpath = length(ep.parts) > 2 ? ep.parts[2] : ""
      method    = ep.method
    }
  ]
  all_endpoints = {
    for ep in local.converted_endpoints :
    "${ep.mainpath}/${ep.subpath != "" ? ep.subpath : "_root"}/${ep.childpath != "" ? ep.childpath : "_root"}/${ep.method}" => ep
  }
  mainpaths = {
    for _, v in local.all_endpoints : v.mainpath => v...
  }
  sub_resources = {
    for _, v in local.all_endpoints :
    "${v.mainpath}/${v.subpath}" => v...
    if v.subpath != ""
  }
  child_resources = {
    for _, v in local.all_endpoints :
    "${v.mainpath}/${v.subpath}/${v.childpath}" => v...
    if v.subpath != "" && v.childpath != ""
  }
}

# API Gateway REST API
resource "aws_api_gateway_rest_api" "rest_api" {
  name        = "${var.product_alias}-${var.env_alias}-rest-api-${var.region}"
  description = "[${var.env_alias}] ${var.product_display_name} REST API"
  endpoint_configuration { types = ["REGIONAL"] }
  tags        = var.tags
}

# API Gateway Resources
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
  for_each    = local.mainpaths
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
  for_each    = local.child_resources
  rest_api_id = aws_api_gateway_rest_api.rest_api.id
  parent_id   = aws_api_gateway_resource.sub["${each.value[0].mainpath}/${each.value[0].subpath}"].id
  path_part   = each.value[0].childpath
}

# API Gateway Methods
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
  http_method   = each.value.method
  authorization = var.create_authorizer ? "CUSTOM" : "NONE"
  authorizer_id = var.create_authorizer ? aws_api_gateway_authorizer.lambda_authorizer[0].id : null
}

# API Gateway Integrations
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
  uri                     = var.lambda_function_invoke_arn
}

# Lambda permission for API Gateway
resource "aws_lambda_permission" "endpoint" {
  action        = "lambda:InvokeFunction"
  function_name = var.lambda_function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.rest_api.execution_arn}/*/*"
}

# API Gateway Deployment
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

# CloudWatch Log Group for API Gateway
resource "aws_cloudwatch_log_group" "api_gateway" {
  name              = "/aws/api-gateway/${var.product_alias}-${var.env_alias}-rest-api"
  retention_in_days = 90
  kms_key_id        = var.cloudwatch_kms_key_arn
}

# IAM Role for CloudWatch integration
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

# API Gateway Stage
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
    })
  }

  depends_on = [aws_api_gateway_account.api_gateway]
}

# Gateway Response for Unauthorized
resource "aws_api_gateway_gateway_response" "unauthorized" {
  rest_api_id   = aws_api_gateway_rest_api.rest_api.id
  response_type = "UNAUTHORIZED"

  status_code = "401"

  response_templates = {
    "application/json" = jsonencode({
      message = "Authentication failed: invalid or missing credentials."
    })
  }
}

# Gateway Response for Access Denied
resource "aws_api_gateway_gateway_response" "access_denied" {
  rest_api_id   = aws_api_gateway_rest_api.rest_api.id
  response_type = "ACCESS_DENIED"

  status_code = "403"

  response_templates = {
    "application/json" = jsonencode({
      message = "Authentication failed: access denied."
    })
  }
}

# Lambda permission for authorizer (conditional)
resource "aws_lambda_permission" "allow_apigw_authorizer" {
  count       = var.create_authorizer ? 1 : 0
  statement_id = "AllowAPIGatewayInvokeAuthorizer"
  action      = "lambda:InvokeFunction"
  function_name = var.authorizer_lambda_function_name
  principal   = "apigateway.amazonaws.com"

  # REST API
  source_arn = "${aws_api_gateway_rest_api.rest_api.execution_arn}/authorizers/*"
}

# API Gateway Authorizer (conditional)
resource "aws_api_gateway_authorizer" "lambda_authorizer" {
  count         = var.create_authorizer ? 1 : 0
  name          = "${var.product_alias}-${var.env_alias}-${var.authorizer.module_name}-${var.authorizer.function_name}"
  rest_api_id   = aws_api_gateway_rest_api.rest_api.id
  authorizer_uri = var.authorizer_lambda_function_invoke_arn

  type                           = "REQUEST"
  identity_source                = "method.request.header.Authorization,context.resourcePath,context.httpMethod"
  authorizer_result_ttl_in_seconds = var.authorizer.result_ttl_in_seconds
}
