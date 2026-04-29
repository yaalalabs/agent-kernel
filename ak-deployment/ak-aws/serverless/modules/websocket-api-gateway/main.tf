# WebSocket API Gateway Module
module "websocket_api" {
  source  = "terraform-aws-modules/apigateway-v2/aws"
  version = "6.1.0"

  # API
  name        = "${var.product_alias}-${var.env_alias}-websocket-api-${var.region}"
  description = "[${var.env_alias}] ${var.product_display_name} WebSocket API"

  # Custom Domain
  create_domain_name = false

  # Websocket
  protocol_type              = "WEBSOCKET"
  route_selection_expression = "$request.body.route"

  # Routes & Integration(s)
  routes = {
    "$connect" = {
      operation_name = "ConnectRoute"
      integration = {
        uri = var.lambda_function_invoke_arn
      }
    },
    "$disconnect" = {
      operation_name = "DisconnectRoute"
      integration = {
        uri = var.lambda_function_invoke_arn
      }
    },
    "$default" = {
      operation_name = "DefaultRoute"
      integration = {
        uri = var.lambda_function_invoke_arn
      }
    },
    "chat" = {
      operation_name = "ChatRoute"
      integration = {
        uri = var.lambda_function_invoke_arn
      }
    }
  }

  # Stage
  stage_name = var.stage_name

  stage_default_route_settings = {
    data_trace_enabled       = var.enable_data_trace
    detailed_metrics_enabled = var.enable_detailed_metrics
    logging_level            = var.logging_level
  }

  stage_access_log_settings = {
    create_log_group            = true
    log_group_retention_in_days = var.cloudwatch_logs_retention_in_days
    log_group_kms_key_arn       = var.cloudwatch_kms_key_arn
    format = jsonencode({
      requestId               = "$context.requestId"
      sourceIp                = "$context.identity.sourceIp"
      requestTime             = "$context.requestTime"
      protocol                = "$context.protocol"
      routeKey                = "$context.routeKey"
      status                  = "$context.status"
      responseLength          = "$context.responseLength"
      integrationErrorMessage = "$context.integrationErrorMessage"
    })
  }

  tags = var.tags
}

# Lambda Permissions for WebSocket API
resource "aws_lambda_permission" "websocket_api" {
  action        = "lambda:InvokeFunction"
  function_name = var.lambda_function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.websocket_api.api_execution_arn}/*"
}
