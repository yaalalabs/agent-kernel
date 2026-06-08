locals {
  enable_autoscaling = var.enable_queue_mode && var.enable_agent_runner_autoscaling
}

# Validation: Autoscaling requires queue mode
resource "null_resource" "validate_autoscaling_requires_queue_mode" {
  count = var.enable_agent_runner_autoscaling && !var.enable_queue_mode ? 1 : 0

  provisioner "local-exec" {
    command = "echo 'ERROR: enable_agent_runner_autoscaling requires enable_queue_mode = true' && exit 1"
  }
}

# ---------- Lambda IAM Role and Policy ----------

resource "aws_iam_role" "backlog_metric_lambda_role" {
  count = local.enable_autoscaling ? 1 : 0
  name  = "${local.prefix}-backlog-metric-lambda-role"

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
  count = local.enable_autoscaling ? 1 : 0
  name  = "${local.prefix}-backlog-metric-lambda-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "GetQueueDepth"
        Effect = "Allow"
        Action = [
          "sqs:GetQueueAttributes"
        ]
        Resource = module.input_queue[0].queue_arn
      },
      {
        Sid    = "GetRunningTaskCount"
        Effect = "Allow"
        Action = [
          "ecs:DescribeServices"
        ]
        Resource = "arn:aws:ecs:${var.region}:${data.aws_caller_identity.current.account_id}:service/${module.ecs.cluster_name}/${local.prefix}-agent-runner"
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
        Resource = "arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.prefix}-backlog-metric:*"
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "backlog_metric_lambda" {
  count      = var.enable_queue_mode ? 1 : 0
  role       = aws_iam_role.backlog_metric_lambda_role[0].name
  policy_arn = aws_iam_policy.backlog_metric_lambda_policy[0].arn
}


data "archive_file" "backlog_metric_lambda" {
  count       = var.enable_queue_mode ? 1 : 0
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
  count            = var.enable_queue_mode ? 1 : 0
  function_name    = "${local.prefix}-backlog-metric"
  role             = aws_iam_role.backlog_metric_lambda_role[0].arn
  runtime          = "python3.12"
  handler          = "index.handler"
  filename         = data.archive_file.backlog_metric_lambda[0].output_path
  source_code_hash = data.archive_file.backlog_metric_lambda[0].output_base64sha256
  timeout          = 30

  environment {
    variables = {
      QUEUE_URL        = module.input_queue[0].queue_url
      CLUSTER_NAME     = module.ecs.cluster_name
      SERVICE_NAME     = "${local.prefix}-agent-runner"
      METRIC_NAMESPACE = "Custom/ECS"
      METRIC_NAME      = "BacklogPerTask"
    }
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "backlog_metric_lambda" {
  count             = var.enable_queue_mode ? 1 : 0
  name              = "/aws/lambda/${local.prefix}-backlog-metric"
  retention_in_days = 7
  tags              = var.tags
}

resource "aws_cloudwatch_event_rule" "backlog_metric_schedule" {
  count               = var.enable_queue_mode ? 1 : 0
  name                = "${local.prefix}-backlog-metric-schedule"
  description         = "Trigger BacklogPerTask metric calculation every minute"
  schedule_expression = "rate(1 minute)"
  tags                = var.tags
}

resource "aws_cloudwatch_event_target" "backlog_metric_lambda" {
  count = local.enable_autoscaling ? 1 : 0
  rule  = aws_cloudwatch_event_rule.backlog_metric_schedule[0].name
  arn   = aws_lambda_function.backlog_metric[0].arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  count         = var.enable_queue_mode ? 1 : 0
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.backlog_metric[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.backlog_metric_schedule[0].arn
}

resource "aws_appautoscaling_target" "agent_runner" {
  count              = var.enable_queue_mode ? 1 : 0
  max_capacity       = var.agent_runner_max_count
  min_capacity       = var.agent_runner_min_count
  resource_id        = "service/${module.ecs.cluster_name}/${local.prefix}-agent-runner"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"

  depends_on = [aws_ecs_service.agent_runner]
}

resource "aws_appautoscaling_policy" "agent_runner_backlog" {
  count              = var.enable_queue_mode ? 1 : 0
  name               = "${local.prefix}-agent-runner-backlog-tracking"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.agent_runner[0].resource_id
  scalable_dimension = aws_appautoscaling_target.agent_runner[0].scalable_dimension
  service_namespace  = aws_appautoscaling_target.agent_runner[0].service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = var.agent_runner_backlog_target
    scale_in_cooldown  = var.agent_runner_scale_in_cooldown
    scale_out_cooldown = var.agent_runner_scale_out_cooldown

    customized_metric_specification {
      namespace   = "Custom/ECS"
      metric_name = "BacklogPerTask"
      statistic   = "Average"

      dimensions {
        name  = "ClusterName"
        value = module.ecs.cluster_name
      }

      dimensions {
        name  = "ServiceName"
        value = "${local.prefix}-agent-runner"
      }
    }
  }
}
