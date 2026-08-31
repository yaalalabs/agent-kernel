# REST Service IAM Policies

resource "aws_iam_policy" "rest_service_sqs_policy" {
  count = var.queue_mode ? 1 : 0

  name        = "${local.prefix}-rest-svc-sqs"
  description = "Allow REST Service ECS task to send to Input Queue and consume from Output Queue"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SendToInputQueue"
        Effect = "Allow"
        Action = [
          "sqs:SendMessage",
          "sqs:GetQueueAttributes",
          "sqs:GetQueueUrl"
        ]
        Resource = module.queues[0].input_queue_arn
      },
      {
        Sid    = "ConsumeOutputQueue"
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:ChangeMessageVisibility",
          "sqs:GetQueueAttributes",
          "sqs:GetQueueUrl"
        ]
        Resource = module.queues[0].output_queue_arn
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_policy" "rest_service_response_store_policy" {
  count = var.queue_mode && !local.is_websocket_mode ? 1 : 0

  name        = "${local.prefix}-rest-svc-response-store"
  description = "Allow REST Service ECS task to read/write the DynamoDB response store"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:DescribeTable",
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Resource = [
          aws_dynamodb_table.response_store[0].arn,
          "${aws_dynamodb_table.response_store[0].arn}/index/*"
        ]
      }
    ]
  })

  tags = var.tags
}

# Scheduling IAM policies (management routes: amend/cancel reach EventBridge Scheduler)

resource "aws_iam_policy" "rest_service_scheduler_policy" {
  count = var.enable_scheduling ? 1 : 0

  name        = "${local.prefix}-rest-svc-scheduler"
  description = "Allow REST Service ECS task to manage EventBridge schedules in the AK schedule group"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ManageSchedules"
        Effect = "Allow"
        Action = [
          "scheduler:CreateSchedule",
          "scheduler:UpdateSchedule",
          "scheduler:DeleteSchedule",
          "scheduler:GetSchedule"
        ]
        Resource = "arn:aws:scheduler:*:${data.aws_caller_identity.current.account_id}:schedule/${local.schedule_group_name}/*"
      },
      {
        # Scheduler assumes the execution role, so registering a schedule passes it.
        Sid      = "PassSchedulerExecutionRole"
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = local.scheduler_execution_role_arn
      }
    ]
  })

  tags = var.tags
}

# The REST service's schedule-store policy lives in modules/rest-service (beside its thread and
# memory table policies, and matching the agent-runner module), so it is attached through that
# module's own task role rather than here.

resource "aws_iam_role_policy_attachment" "rest_service_sqs_attachment" {
  count      = var.queue_mode ? 1 : 0
  role       = module.rest_service.task_role_name
  policy_arn = aws_iam_policy.rest_service_sqs_policy[0].arn
}

resource "aws_iam_role_policy_attachment" "rest_service_response_store_attachment" {
  count      = var.queue_mode && !local.is_websocket_mode ? 1 : 0
  role       = module.rest_service.task_role_name
  policy_arn = aws_iam_policy.rest_service_response_store_policy[0].arn
}

resource "aws_iam_role_policy_attachment" "rest_service_scheduler_attachment" {
  count      = var.enable_scheduling ? 1 : 0
  role       = module.rest_service.task_role_name
  policy_arn = aws_iam_policy.rest_service_scheduler_policy[0].arn
}

# REST service WebSocket IAM policies (async / stream modes)

# Push messages to connected clients (PostToConnection).
resource "aws_iam_policy" "rest_service_websocket_api_policy" {
  count = local.is_websocket_mode ? 1 : 0

  name        = "${local.prefix}-rest-svc-websocket-api"
  description = "Allow REST Service ECS task to manage WebSocket connections (PostToConnection)"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["execute-api:ManageConnections"]
        Resource = "${aws_apigatewayv2_api.ws_api[0].execution_arn}/*"
      }
    ]
  })

  tags = var.tags
}

# Read/write the WebSocket connections table.
resource "aws_iam_policy" "rest_service_websocket_connections_policy" {
  count = local.is_websocket_mode ? 1 : 0

  name        = "${local.prefix}-rest-svc-websocket-connections"
  description = "Allow REST Service ECS task to read/write the WebSocket connections table"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:DescribeTable",
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Resource = [
          module.websocket_connections[0].table_arn,
          "${module.websocket_connections[0].table_arn}/index/*"
        ]
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "rest_service_websocket_api_attachment" {
  count      = local.is_websocket_mode ? 1 : 0
  role       = module.rest_service.task_role_name
  policy_arn = aws_iam_policy.rest_service_websocket_api_policy[0].arn
}

resource "aws_iam_role_policy_attachment" "rest_service_websocket_connections_attachment" {
  count      = local.is_websocket_mode ? 1 : 0
  role       = module.rest_service.task_role_name
  policy_arn = aws_iam_policy.rest_service_websocket_connections_policy[0].arn
}
