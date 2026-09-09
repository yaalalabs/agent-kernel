# EventBridge Scheduler resources for the scheduling capability.
# The application owns the schedules themselves (one per scheduled task, created at runtime through
# `AKConfig.schedule.provider.type: eventbridge`); Terraform only provisions the group they live in
# and the role Scheduler assumes to deliver each trigger to the Input Queue.

check "scheduling_requires_queue_mode" {
  assert {
    condition     = var.enable_scheduling ? var.queue_mode : true
    error_message = "[IMPORTANT] enable_scheduling requires queue_mode = true: EventBridge Scheduler delivers its triggers to the Input Queue, which only exists in queue mode."
  }
}

resource "aws_scheduler_schedule_group" "schedules" {
  count = var.enable_scheduling ? 1 : 0

  name = "${local.prefix}-schedules"

  tags = merge(var.tags, { Type = "ScheduleGroup" })
}

# Execution role Scheduler assumes per occurrence to send the trigger to the Input Queue.
# The application passes this role's ARN when it registers a schedule, which is why both task roles
# also need iam:PassRole on it (see iam.tf and modules/agent-runner/main.tf).

resource "aws_iam_role" "scheduler_execution" {
  count = var.enable_scheduling ? 1 : 0

  name        = "${local.prefix}-scheduler-exec-role"
  description = "Role EventBridge Scheduler assumes to deliver scheduled triggers to the Input Queue"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "scheduler.amazonaws.com" }
      Condition = {
        StringEquals = {
          "aws:SourceAccount" = data.aws_caller_identity.current.account_id
        }
      }
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "scheduler_send_to_input_queue" {
  count = var.enable_scheduling ? 1 : 0

  name = "${local.prefix}-scheduler-send-to-input-queue"
  role = aws_iam_role.scheduler_execution[0].id

  # No KMS statement: the queues use SQS-managed SSE, not a customer-managed key.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sqs:SendMessage"]
      Resource = module.queues[0].input_queue_arn
    }]
  })
}
