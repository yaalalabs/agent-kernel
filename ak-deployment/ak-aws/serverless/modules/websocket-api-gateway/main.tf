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
  routes = merge(
    {
      "$connect" = {
        operation_name = "ConnectRoute"
        integration = {
          uri = var.connection_handler_lambda_invoke_arn
        }
      },
      "$disconnect" = {
        operation_name = "DisconnectRoute"
        integration = {
          uri = var.connection_handler_lambda_invoke_arn
        }
      },
      "$default" = {
        operation_name = "DefaultRoute"
        integration = {
          uri = var.route_handler_lambda_invoke_arn
        }
      },
      "${var.chat_route}" = {
        operation_name = "ChatRoute"
        integration = {
          uri = var.route_handler_lambda_invoke_arn
        }
      }
    },
    {
      for custom_route in var.custom_routes :
      custom_route.route => {
        operation_name = "${custom_route.route}Route"
        integration = {
          uri = var.route_handler_lambda_invoke_arn
        }
      }
    }
  )

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

# Access for Websocket API Gateway to invoke the route handler lambda
resource "aws_lambda_permission" "websocket_api" {
  action        = "lambda:InvokeFunction"
  function_name = var.route_handler_lambda_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.websocket_api.api_execution_arn}/*"
}

# Access for Websocket API Gateway to invoke the connection handler lambda
resource "aws_lambda_permission" "websocket_connection_handler" {
  action        = "lambda:InvokeFunction"
  function_name = var.connection_handler_lambda_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.websocket_api.api_execution_arn}/*"
}

# IAM policy for route handler Lambda to call PostToConnection on WebSocket API
resource "aws_iam_policy" "route_handler_websocket_api_policy" {
  count = var.route_handler_lambda_role_name != null ? 1 : 0
  name  = "${var.product_alias}-${var.env_alias}-route-handler-websocket-api"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "execute-api:ManageConnections"
        ]
        Resource = "${module.websocket_api.api_execution_arn}/*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "route_handler_websocket_api_attachment" {
  count      = var.route_handler_lambda_role_name != null ? 1 : 0
  role       = var.route_handler_lambda_role_name
  policy_arn = aws_iam_policy.route_handler_websocket_api_policy[0].arn
}
