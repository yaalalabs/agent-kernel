variable "region" {
  type        = string
  description = "Region"
}

variable "product_alias" {
  type        = string
  description = "Product alias"
}

variable "env_alias" {
  type        = string
  description = "Environment alias"
}

variable "module_type" {
  type        = string
  description = "Module type"
  default     = "python"
}

variable "module_name" {
  type        = string
  description = "Module name"
}

variable "is_production" {
  description = "Is production"
  type        = bool
  default     = false
}

variable "package_path" {
  type        = string
  description = "Zip package path or Docker image source path"
}

variable "scalable_mode" {
  type        = bool
  description = "When true, response_handler lambda will be created along with the response "
  default     = true
}

variable "event_source_mapping" {
  description = "Event source mapping"
  type        = any
  default = []
}

variable "environment_variables" {
  description = "Environment variables"
  type        = any
  default = {}
}

variable "timeout" {
  description = "Lambda timeout"
  type        = number
  default     = 30
}

variable "memory_size" {
  description = "Lambda memory size"
  type        = number
  default     = 128
}

variable "function_name" {
  description = "Lambda function name"
  type        = string
}

variable "function_description" {
  description = "Lambda function description"
  type        = string
}

variable "handler_path" {
  description = "Lambda handler path"
  type        = string
}

variable "package_type" {
  description = "Lambda deployment type Image/LocalZip/S3Zip"
  type        = string
  default     = "LocalZip"
}

variable "layers" {
  description = "Lambda layers"
  type = list(string)
  default = []
}

variable "api_version" {
  type        = string
  description = "API version"
  default     = "v1"
}

variable "agent_endpoint" {
  type        = string
  description = "Agent invocation endpoint"
  default     = "chat"
}

variable "api_base_path" {
  type        = string
  description = "Optional base path segment for the API (e.g., 'api'). Set to null or empty to omit."
  default     = "api"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID"
}

variable "subnet_ids" {
  type = list(string)
  description = "Subnet IDs for VPC deployment"
}

variable "create_dynamodb_memory_table" {
  type        = bool
  description = "Create a dynamodb table to store the Agent memory"
  default     = false
}

variable "create_dynamodb_multimodal_memory_table" {
  type        = bool
  description = "Create a dynamodb table to store the Agent multimodal memory"
  default     = false
}

variable "dynamodb_memory_table_arn" {
  type        = string
  description = "ARN of the DynamoDB memory table"
  default     = null
}

variable "dynamodb_memory_table_name" {
  type        = string
  description = "Name of the DynamoDB memory table"
  default     = null
}

variable "dynamodb_multimodal_memory_table_arn" {
  type        = string
  description = "ARN of the DynamoDB multimodal memory table"
  default     = null
}

variable "dynamodb_multimodal_memory_table_name" {
  type        = string
  description = "Name of the DynamoDB multimodal memory table"
  default     = null
}

variable "input_queue_arn" {
  type        = string
  description = "ARN of the input SQS queue"
  default     = null
}

variable "input_queue_url" {
  type        = string
  description = "URL of the input SQS queue"
  default     = null
}

variable "redis_url" {
  type        = string
  description = "URL of the Redis cluster"
  default     = null
}

variable "lambda_signer_profile_name" {
  type        = string
  description = "AWS Signer profile name"
  default     = "sample_profile"
}

variable "lambda_signing_config_arn" {
  type        = string
  description = "ARN of the Lambda code signing configuration"
  default     = null
}

variable "docker_image_uri" {
  type        = string
  description = "Docker image URI for Image package type"
  default     = null
}

variable "lambda_kms_key_arn" {
  type        = string
  description = "ARN of the KMS key for Lambda encryption"
  default     = null
}

variable "cloudwatch_kms_key_arn" {
  type        = string
  description = "ARN of the KMS key for CloudWatch logs encryption"
  default     = null
}

variable "product_display_name" {
  type        = string
  description = "Product display name"
  default     = null
}

variable "websocket_connections_table_name" {
  type        = string
  description = "Name of the WebSocket connections DynamoDB table"
  default     = null
}

variable "websocket_connections_table_arn" {
  type        = string
  description = "ARN of the WebSocket connections DynamoDB table"
  default     = null
}
