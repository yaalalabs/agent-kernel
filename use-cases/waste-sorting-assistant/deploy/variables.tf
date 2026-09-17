variable "region" {
  description = "AWS region for the deployment."
  type        = string
  default     = "us-east-1"
}

variable "prefix" {
  type        = string
  description = "Prefix applied to every resource name"
}

variable "openai_api_key" {
  description = "OpenAI API key passed to the Lambda runtime."
  type        = string
  sensitive   = true
}
