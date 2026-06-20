# ---------- REST Service IAM Policies ----------

resource "aws_iam_policy" "rest_service_sqs_policy" {
  count = var.enable_queue_mode ? 1 : 0

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
  count = var.enable_queue_mode ? 1 : 0

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

resource "aws_iam_role_policy_attachment" "rest_service_sqs_attachment" {
  count      = var.enable_queue_mode ? 1 : 0
  role       = module.rest_service.task_role_name
  policy_arn = aws_iam_policy.rest_service_sqs_policy[0].arn
}

resource "aws_iam_role_policy_attachment" "rest_service_response_store_attachment" {
  count      = var.enable_queue_mode ? 1 : 0
  role       = module.rest_service.task_role_name
  policy_arn = aws_iam_policy.rest_service_response_store_policy[0].arn
}
