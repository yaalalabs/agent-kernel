locals {
  queue_name = "${var.product_alias}-${var.env_alias}-${var.module_name}-${var.queue_name}.fifo"
  dlq_name   = "${var.product_alias}-${var.env_alias}-${var.module_name}-${var.queue_name}-dlq.fifo"
}

data "aws_caller_identity" "current" {}

# Main FIFO Queue with integrated DLQ using terraform-aws-modules
module "sqs_fifo_queue" {
  source  = "terraform-aws-modules/sqs/aws"
  version = "5.2.1"

  name                            = local.queue_name
  fifo_queue                      = true
  content_based_deduplication     = var.content_based_deduplication
  max_message_size                = var.max_message_size
  message_retention_seconds       = var.message_retention_seconds
  visibility_timeout_seconds      = var.visibility_timeout_seconds
  fifo_throughput_limit           = var.fifo_throughput_limit
  deduplication_scope             = var.deduplication_scope
  sqs_managed_sse_enabled         = var.sqs_managed_sse_enabled
  # KMS Related variables won't be needed if sqs_managed_sse_enabled is true
  kms_master_key_id               = var.kms_master_key_id 
  kms_data_key_reuse_period_seconds = var.kms_data_key_reuse_period_seconds

  # Dead Letter Queue configuration (integrated)
  create_dlq                      = true
  dlq_name                        = local.dlq_name
  dlq_message_retention_seconds   = var.dlq_message_retention_seconds
  dlq_visibility_timeout_seconds  = var.visibility_timeout_seconds
  dlq_sqs_managed_sse_enabled     = var.sqs_managed_sse_enabled
  # KMS Related variables won't be needed if sqs_managed_sse_enabled is true
  dlq_kms_master_key_id           = var.kms_master_key_id
  dlq_kms_data_key_reuse_period_seconds = var.kms_data_key_reuse_period_seconds

  # Redrive policy for DLQ
  redrive_policy = {
    maxReceiveCount = var.max_receive_count
  }

  # Producer access policy
  create_queue_policy = var.enable_producer_access
  queue_policy_statements = var.enable_producer_access ? {
    AllowProducerSendMessage = {
      sid    = "AllowProducerSendMessage"
      effect = "Allow"
      principals = [
        {
          type        = "AWS"
          identifiers = var.producer_arns
        }
      ]
      actions = ["sqs:SendMessage"]
    }
  } : {}

  tags = merge({
    Name         = local.queue_name
    Region       = var.region
    ResourceName = "SQS FIFO Queue"
  }, var.tags)
}

# Consumer access policy (separate from main queue policy)
data "aws_iam_policy_document" "consumer_access" {
  count = var.enable_consumer_access ? 1 : 0

  statement {
    sid    = "AllowConsumerReceiveMessage"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = var.consumer_role_arns
    }

    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility",
      "sqs:GetQueueAttributes"
    ]

    resources = [module.main.queue_arn]
  }
}

# Apply consumer policy to main queue
resource "aws_sqs_queue_policy" "consumer_policy" {
  count     = var.enable_consumer_access ? 1 : 0
  queue_url = module.main.queue_url
  policy    = data.aws_iam_policy_document.consumer_access[0].json
}