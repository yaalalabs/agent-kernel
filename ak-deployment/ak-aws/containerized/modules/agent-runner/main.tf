locals {
  agent_runner_image = var.agent_runner.image_uri != null ? var.agent_runner.image_uri : var.default_image_uri
  
  agent_runner_environment = merge(
    var.agent_runner.environment_variables,
    {
      AK_EXECUTION__QUEUES__INPUT__URL               = var.input_queue_url
      AK_EXECUTION__QUEUES__OUTPUT__URL              = var.output_queue_url
      AK_EXECUTION__QUEUES__INPUT__MAX_RECEIVE_COUNT = tostring(max(1, var.queue_config.input_queue_max_receive_count - 1))
    },
    var.redis_url != null ? { AK_SESSION__REDIS__URL = var.redis_url } : {},
    var.dynamodb_memory_table_arn != null ? {
      AK_SESSION__DYNAMODB__TABLE_NAME = var.dynamodb_memory_table_name
    } : {}
  )
}

# ---------- IAM Roles ----------

resource "aws_iam_role" "agent_runner_execution_role" {
  name = "${var.prefix}-agent-runner-exec-role"

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
  role       = aws_iam_role.agent_runner_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "agent_runner_task_role" {
  name = "${var.prefix}-agent-runner-task-role"

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

# ---------- IAM Policies ----------

resource "aws_iam_policy" "agent_runner_logs_policy" {
  name = "${var.prefix}-agent-runner-logs"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ]
      Resource = "arn:aws:logs:${var.region}:*:log-group:/ecs/${var.prefix}-agent-runner:*"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "agent_runner_logs_attachment" {
  role       = aws_iam_role.agent_runner_task_role.name
  policy_arn = aws_iam_policy.agent_runner_logs_policy.arn
}

resource "aws_iam_policy" "agent_runner_sqs_policy" {
  name        = "${var.prefix}-agent-runner-sqs"
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
        Resource = var.input_queue_arn
      },
      {
        Sid    = "SendToOutputQueue"
        Effect = "Allow"
        Action = [
          "sqs:SendMessage",
          "sqs:GetQueueAttributes",
          "sqs:GetQueueUrl"
        ]
        Resource = var.output_queue_arn
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "agent_runner_sqs_attachment" {
  role       = aws_iam_role.agent_runner_task_role.name
  policy_arn = aws_iam_policy.agent_runner_sqs_policy.arn
}

resource "aws_iam_policy" "agent_runner_dynamodb_memory_policy" {
  count = var.dynamodb_memory_table_arn != null ? 1 : 0
  name  = "${var.prefix}-agent-runner-dynamodb-memory"

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
        var.dynamodb_memory_table_arn,
        "${var.dynamodb_memory_table_arn}/index/*"
      ]
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "agent_runner_dynamodb_memory_attachment" {
  count      = var.dynamodb_memory_table_arn != null ? 1 : 0
  role       = aws_iam_role.agent_runner_task_role.name
  policy_arn = aws_iam_policy.agent_runner_dynamodb_memory_policy[0].arn
}

# ---------- ECS Resources ----------

resource "aws_security_group" "agent_runner" {
  name        = "${var.prefix}-agent-runner-sg"
  description = "Agent Runner ECS service SG - egress only (queue-polling)"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "agent_runner" {
  name              = "/ecs/${var.prefix}-agent-runner"
  retention_in_days = 90
  tags              = var.tags
}

resource "aws_ecs_task_definition" "agent_runner" {
  family                   = "${var.prefix}-agent-runner"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.agent_runner.cpu
  memory                   = var.agent_runner.memory
  execution_role_arn       = aws_iam_role.agent_runner_execution_role.arn
  task_role_arn            = aws_iam_role.agent_runner_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "${var.prefix}-agent-runner"
      image     = local.agent_runner_image
      essential = true

      # Command override - if provided, replaces the Docker image's CMD
      command = var.agent_runner.command

      environment = [
        for k, v in local.agent_runner_environment : { name = k, value = v }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/${var.prefix}-agent-runner"
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])

  tags = var.tags
}

resource "aws_ecs_service" "agent_runner" {
  name            = "${var.prefix}-agent-runner"
  cluster         = var.ecs_cluster_arn
  task_definition = aws_ecs_task_definition.agent_runner.arn
  desired_count   = var.agent_runner.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [aws_security_group.agent_runner.id]
    assign_public_ip = false
  }

  tags = var.tags
  
  lifecycle {
    ignore_changes = [desired_count]
  }
}

# ---------- Auto Scaling ----------

resource "aws_iam_role" "backlog_metric_lambda_role" {
  count = var.scaling_config.enabled ? 1 : 0
  name  = "${var.prefix}-backlog-metric-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = var.tags
}

resource "aws_iam_policy" "backlog_metric_lambda_policy" {
  count = var.scaling_config.enabled ? 1 : 0
  name  = "${var.prefix}-backlog-metric-lambda-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "GetQueueDepth"
        Effect = "Allow"
        Action = [
          "sqs:GetQueueAttributes"
        ]
        Resource = var.input_queue_arn
      },
      {
        Sid    = "GetRunningTaskCount"
        Effect = "Allow"
        Action = [
          "ecs:DescribeServices"
        ]
        Resource = "arn:aws:ecs:${var.region}:${var.account_id}:service/${var.ecs_cluster_name}/${var.prefix}-agent-runner"
      },
      {
        Sid      = "PutCustomMetric"
        Effect   = "Allow"
        Action   = "cloudwatch:PutMetricData"
        Resource = "*"
      },
      {
        Sid    = "LambdaLogging"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.region}:${var.account_id}:log-group:/aws/lambda/${var.prefix}-backlog-metric:*"
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "backlog_metric_lambda" {
  count      = var.scaling_config.enabled ? 1 : 0
  role       = aws_iam_role.backlog_metric_lambda_role[0].name
  policy_arn = aws_iam_policy.backlog_metric_lambda_policy[0].arn
}

data "archive_file" "backlog_metric_lambda" {
  count       = var.scaling_config.enabled ? 1 : 0
  type        = "zip"
  output_path = "${path.module}/.terraform/lambda/backlog_metric.zip"

  source {
    content  = <<-PYTHON
import boto3
import os
import json

def handler(event, context):
    """
    Calculate BacklogPerTask metric for ECS agent runner autoscaling.
    
    BacklogPerTask = ApproximateNumberOfMessages / max(runningCount, 1)
    
    This metric is used by Target Tracking Scaling to adjust the number
    of agent runner tasks based on queue depth.
    """
    sqs = boto3.client("sqs")
    ecs = boto3.client("ecs")
    cw = boto3.client("cloudwatch")
    
    queue_url = os.environ["QUEUE_URL"]
    cluster_name = os.environ["CLUSTER_NAME"]
    service_name = os.environ["SERVICE_NAME"]
    namespace = os.environ.get("METRIC_NAMESPACE", "Custom/ECS")
    metric_name = os.environ.get("METRIC_NAME", "BacklogPerTask")
    
    # --- Get queue depth ---
    attrs = sqs.get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=["ApproximateNumberOfMessages"]
    )
    queue_depth = int(attrs["Attributes"]["ApproximateNumberOfMessages"])
    
    # --- Get running task count ---
    resp = ecs.describe_services(cluster=cluster_name, services=[service_name])
    running = resp["services"][0]["runningCount"]
    
    # Avoid division by zero; treat 0 running tasks as 1 for the metric
    divisor = max(running, 1)
    backlog_per_task = queue_depth / divisor
    
    # --- Publish custom metric ---
    cw.put_metric_data(
        Namespace=namespace,
        MetricData=[{
            "MetricName": metric_name,
            "Value": backlog_per_task,
            "Unit": "Count",
            "Dimensions": [
                {"Name": "ClusterName", "Value": cluster_name},
                {"Name": "ServiceName", "Value": service_name},
            ]
        }]
    )
    
    print(f"Published metric: {metric_name}={backlog_per_task} (queue_depth={queue_depth}, running={running})")
    
    return {
        "backlog_per_task": backlog_per_task,
        "queue_depth": queue_depth,
        "running": running
    }
PYTHON
    filename = "index.py"
  }
}

resource "aws_lambda_function" "backlog_metric" {
  count            = var.scaling_config.enabled ? 1 : 0
  function_name    = "${var.prefix}-backlog-metric"
  role             = aws_iam_role.backlog_metric_lambda_role[0].arn
  runtime          = "python3.12"
  handler          = "index.handler"
  filename         = data.archive_file.backlog_metric_lambda[0].output_path
  source_code_hash = data.archive_file.backlog_metric_lambda[0].output_base64sha256
  timeout          = 30

  environment {
    variables = {
      QUEUE_URL        = var.input_queue_url
      CLUSTER_NAME     = var.ecs_cluster_name
      SERVICE_NAME     = "${var.prefix}-agent-runner"
      METRIC_NAMESPACE = "Custom/ECS"
      METRIC_NAME      = "BacklogPerTask"
    }
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "backlog_metric_lambda" {
  count             = var.scaling_config.enabled ? 1 : 0
  name              = "/aws/lambda/${var.prefix}-backlog-metric"
  retention_in_days = 7
  tags              = var.tags
}

resource "aws_cloudwatch_event_rule" "backlog_metric_schedule" {
  count               = var.scaling_config.enabled ? 1 : 0
  name                = "${var.prefix}-backlog-metric-schedule"
  description         = "Trigger BacklogPerTask metric calculation every minute"
  schedule_expression = "rate(1 minute)"
  tags                = var.tags
}

resource "aws_cloudwatch_event_target" "backlog_metric_lambda" {
  count = var.scaling_config.enabled ? 1 : 0
  rule  = aws_cloudwatch_event_rule.backlog_metric_schedule[0].name
  arn   = aws_lambda_function.backlog_metric[0].arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  count         = var.scaling_config.enabled ? 1 : 0
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.backlog_metric[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.backlog_metric_schedule[0].arn
}

resource "aws_appautoscaling_target" "agent_runner" {
  count              = var.scaling_config.enabled ? 1 : 0
  max_capacity       = var.scaling_config.max_count
  min_capacity       = var.scaling_config.min_count
  resource_id        = "service/${var.ecs_cluster_name}/${var.prefix}-agent-runner"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"

  depends_on = [aws_ecs_service.agent_runner]
}

resource "aws_appautoscaling_policy" "agent_runner_backlog" {
  count              = var.scaling_config.enabled ? 1 : 0
  name               = "${var.prefix}-agent-runner-backlog-tracking"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.agent_runner[0].resource_id
  scalable_dimension = aws_appautoscaling_target.agent_runner[0].scalable_dimension
  service_namespace  = aws_appautoscaling_target.agent_runner[0].service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = var.scaling_config.backlog_target
    scale_in_cooldown  = var.scaling_config.scale_in_cooldown
    scale_out_cooldown = var.scaling_config.scale_out_cooldown

    customized_metric_specification {
      namespace   = "Custom/ECS"
      metric_name = "BacklogPerTask"
      statistic   = "Average"

      dimensions {
        name  = "ClusterName"
        value = var.ecs_cluster_name
      }

      dimensions {
        name  = "ServiceName"
        value = "${var.prefix}-agent-runner"
      }
    }
  }
}
