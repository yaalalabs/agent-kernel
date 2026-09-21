variable "region" {
  description = "AWS region for the deployment."
  type        = string
  default     = "us-east-1"
}

variable "prefix" {
  description = "Prefix applied to every resource name."
  type        = string
  default     = "ak-dev-waste-sorting"
}

variable "openai_api_key" {
  description = "OpenAI API key passed to the Lambda runtime."
  type        = string
  sensitive   = true
}
