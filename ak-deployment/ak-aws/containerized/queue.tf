data "aws_region" "current" {}


module "input_queue" {
  count  = var.enable_queue_mode ? 1 : 0
  source = "../common/modules/sqs"

  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  queue_name           = "input-queue"
  region               = data.aws_region.current.name
  product_display_name = var.product_alias
  is_production        = var.env_alias == "prod"

  fifo_queue                  = true
  content_based_deduplication = false
  deduplication_scope         = "messageGroup"
  fifo_throughput_limit       = "perMessageGroupId"

  visibility_timeout_seconds = var.sqs_input_visibility_timeout
  message_retention_seconds  = var.sqs_input_message_retention_seconds
  max_message_size           = var.sqs_max_message_size
  receive_wait_time_seconds  = var.sqs_receive_wait_time_seconds
  max_receive_count          = var.sqs_input_max_receive_count
  create_dlq                 = var.sqs_input_create_dlq
  dlq_message_retention_seconds = var.sqs_input_dlq_message_retention_seconds

  sqs_managed_sse_enabled = var.sqs_managed_sse_enabled

  # IAM access is managed via ECS task role policies below
  enable_producer_access = false
  enable_consumer_access = false

  tags = merge(var.tags, { Type = "InputQueue" })
}

module "output_queue" {
  count  = var.enable_queue_mode ? 1 : 0
  source = "../common/modules/sqs"

  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  queue_name           = "output-queue"
  region               = data.aws_region.current.name
  product_display_name = var.product_alias
  is_production        = var.env_alias == "prod"

  fifo_queue                  = true
  content_based_deduplication = false
  deduplication_scope         = "messageGroup"
  fifo_throughput_limit       = "perMessageGroupId"

  visibility_timeout_seconds = var.sqs_output_visibility_timeout
  message_retention_seconds  = var.sqs_output_message_retention_seconds
  max_message_size           = var.sqs_max_message_size
  receive_wait_time_seconds  = var.sqs_receive_wait_time_seconds
  max_receive_count          = var.sqs_output_max_receive_count
  create_dlq                 = var.sqs_output_create_dlq
  dlq_message_retention_seconds = var.sqs_output_dlq_message_retention_seconds

  sqs_managed_sse_enabled = var.sqs_managed_sse_enabled

  enable_producer_access = false
  enable_consumer_access = false

  tags = merge(var.tags, { Type = "OutputQueue" })
}

resource "aws_dynamodb_table" "response_store" {
  count = var.enable_queue_mode ? 1 : 0

  name         = "${local.prefix}-response-store"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "request_id"

  attribute {
    name = "request_id"
    type = "S"
  }

  ttl {
    attribute_name = "expiry_time"
    enabled        = true
  }

  tags = merge(var.tags, { Type = "ResponseStore" })
}


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
        Resource = module.input_queue[0].queue_arn
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
        Resource = module.output_queue[0].queue_arn
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
  role       = module.ecs.services[local.service_name].tasks_iam_role_name
  policy_arn = aws_iam_policy.rest_service_sqs_policy[0].arn
}

resource "aws_iam_role_policy_attachment" "rest_service_response_store_attachment" {
  count      = var.enable_queue_mode ? 1 : 0
  role       = module.ecs.services[local.service_name].tasks_iam_role_name
  policy_arn = aws_iam_policy.rest_service_response_store_policy[0].arn
}


resource "aws_iam_role" "agent_runner_execution_role" {
  count = var.enable_queue_mode ? 1 : 0

  name = "${local.prefix}-agent-runner-exec-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "agent_runner_execution_policy" {
  count      = var.enable_queue_mode ? 1 : 0
  role       = aws_iam_role.agent_runner_execution_role[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "agent_runner_task_role" {
  count = var.enable_queue_mode ? 1 : 0

  name = "${local.prefix}-agent-runner-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })

  tags = var.tags
}


resource "aws_iam_policy" "agent_runner_logs_policy" {
  count = var.enable_queue_mode ? 1 : 0
  name  = "${local.prefix}-agent-runner-logs"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ]
      Resource = "arn:aws:logs:${var.region}:*:log-group:/ecs/${local.prefix}-agent-runner:*"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "agent_runner_logs_attachment" {
  count      = var.enable_queue_mode ? 1 : 0
  role       = aws_iam_role.agent_runner_task_role[0].name
  policy_arn = aws_iam_policy.agent_runner_logs_policy[0].arn
}

resource "aws_iam_policy" "agent_runner_sqs_policy" {
  count = var.enable_queue_mode ? 1 : 0

  name        = "${local.prefix}-agent-runner-sqs"
  description = "Allow Agent Runner ECS task to consume Input Queue and produce to Output Queue"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ConsumeInputQueue"
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:ChangeMessageVisibility",
          "sqs:GetQueueAttributes",
          "sqs:GetQueueUrl"
        ]
        Resource = module.input_queue[0].queue_arn
      },
      {
        Sid    = "SendToOutputQueue"
        Effect = "Allow"
        Action = [
          "sqs:SendMessage",
          "sqs:GetQueueAttributes",
          "sqs:GetQueueUrl"
        ]
        Resource = module.output_queue[0].queue_arn
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "agent_runner_sqs_attachment" {
  count      = var.enable_queue_mode ? 1 : 0
  role       = aws_iam_role.agent_runner_task_role[0].name
  policy_arn = aws_iam_policy.agent_runner_sqs_policy[0].arn
}

# DynamoDB session store access for agent runner (same table as REST Service)
resource "aws_iam_policy" "agent_runner_dynamodb_memory_policy" {
  count = var.enable_queue_mode && var.create_dynamodb_memory_table ? 1 : 0
  name  = "${local.prefix}-agent-runner-dynamodb-memory"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
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
        local.dynamodb_memory_table_arn,
        "${local.dynamodb_memory_table_arn}/index/*"
      ]
    }]
  })
}

resource "aws_iam_role_policy_attachment" "agent_runner_dynamodb_memory_attachment" {
  count      = var.enable_queue_mode && var.create_dynamodb_memory_table ? 1 : 0
  role       = aws_iam_role.agent_runner_task_role[0].name
  policy_arn = aws_iam_policy.agent_runner_dynamodb_memory_policy[0].arn
}

# ---------- ECS Agent Runner Service ----------

resource "aws_security_group" "agent_runner" {
  count = var.enable_queue_mode ? 1 : 0

  name        = "${local.prefix}-agent-runner-sg"
  description = "Agent Runner ECS service SG - egress only (queue-polling)"
  vpc_id      = local.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "agent_runner" {
  count             = var.enable_queue_mode ? 1 : 0
  name              = "/ecs/${local.prefix}-agent-runner"
  retention_in_days = 90
  tags              = var.tags
}

resource "aws_ecs_task_definition" "agent_runner" {
  count = var.enable_queue_mode ? 1 : 0

  family                   = "${local.prefix}-agent-runner"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.agent_runner_cpu
  memory                   = var.agent_runner_memory
  execution_role_arn       = aws_iam_role.agent_runner_execution_role[0].arn
  task_role_arn            = aws_iam_role.agent_runner_task_role[0].arn

  container_definitions = jsonencode([
    {
      name      = "${local.prefix}-agent-runner"
      image     = var.agent_runner_image_uri != null ? var.agent_runner_image_uri : module.docker_image[0].docker_image_uri
      essential = true

      # Command override - if provided, replaces the Docker image's CMD
      command = var.agent_runner_command

      environment = [
        for k, v in merge(
          var.environment_variables,
          {
            AK_EXECUTION__QUEUES__INPUT__URL               = module.input_queue[0].queue_url
            AK_EXECUTION__QUEUES__OUTPUT__URL              = module.output_queue[0].queue_url
            AK_EXECUTION__QUEUES__INPUT__MAX_RECEIVE_COUNT = tostring(max(1, var.sqs_input_max_receive_count - 1))
          },
          local.redis_url != null ? { AK_SESSION__REDIS__URL = local.redis_url } : {},
          local.dynamodb_memory_table_arn != null ? {
            AK_SESSION__DYNAMODB__TABLE_NAME = local.dynamodb_memory_table_name
          } : {}
        ) : { name = k, value = v }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/${local.prefix}-agent-runner"
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])

  tags = var.tags
}

resource "aws_ecs_service" "agent_runner" {
  count = var.enable_queue_mode ? 1 : 0

  name            = "${local.prefix}-agent-runner"
  cluster         = module.ecs.cluster_arn
  task_definition = aws_ecs_task_definition.agent_runner[0].arn
  desired_count   = var.agent_runner_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = local.subnet_ids
    security_groups  = [aws_security_group.agent_runner[0].id]
    assign_public_ip = false
  }

  tags = var.tags
}

# Only needed for rest_async mode — adds GET /api/{version}/{endpoint}/{sessionId}

resource "aws_apigatewayv2_integration" "async_get" {
  count                = var.enable_queue_mode && var.queue_mode_type == "async" ? 1 : 0
  api_id               = aws_apigatewayv2_api.http_api.id
  integration_type     = "HTTP_PROXY"
  integration_method   = "ANY"
  integration_uri      = aws_lb_listener.http.arn
  connection_type      = "VPC_LINK"
  connection_id        = aws_apigatewayv2_vpc_link.ecs_alb.id
  passthrough_behavior = "WHEN_NO_MATCH"

  request_parameters = {
    "overwrite:path" = "/api/v1/chat/$request.path.sessionId"
  }
}

resource "aws_apigatewayv2_route" "async_get" {
  count     = var.enable_queue_mode && var.queue_mode_type == "async" ? 1 : 0
  api_id    = aws_apigatewayv2_api.http_api.id
  route_key = "GET ${local.api_base_segment_with_version}/${var.agent_endpoint}/{sessionId}"
  target    = "integrations/${aws_apigatewayv2_integration.async_get[0].id}"
}
