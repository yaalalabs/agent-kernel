variable "region" {
  description = "AWS region for the deployment."
  type        = string
  default     = "us-east-1"
}

variable "product_alias" {
  description = "Short product alias used to name AWS resources."
  type        = string
  default     = "ak"
}

variable "env_alias" {
  description = "Environment alias used to name AWS resources."
  type        = string
  default     = "dev"
}

variable "module_name" {
  description = "Module name used to namespace AWS resources."
  type        = string
  default     = "waste-sorting"
}

variable "openai_api_key" {
  description = "OpenAI API key passed to the Lambda runtime."
  type        = string
  sensitive   = true
}

variable "dynamodb_session_table_name" {
  description = "Optional override for the Agent Kernel DynamoDB session table name."
  type        = string
  default     = null
}

variable "ak_log_level" {
  description = "Agent Kernel log level for Lambda."
  type        = string
  default     = "INFO"
}
