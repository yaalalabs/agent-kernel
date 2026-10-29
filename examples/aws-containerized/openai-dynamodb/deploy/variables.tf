variable "region" {
  type        = string
  description = "Region"
}

variable "prefix" {
  type        = string
  description = "Prefix applied to every resource name"
}

variable "is_production" {
  description = "Is production"
  type        = bool
  default     = false
}

variable "openai_api_key" {
  description = "OpenAI API Key"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID for ECS deployment"
  type        = string
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for ECS deployment"
  type        = list(string)
}

variable "alb_security_group_id" {
  description = "ALB security group ID. If not provided, a new one will be created"
  type        = string
  default     = null
}

variable "ecs_service_security_group_id" {
  description = "ECS service security group ID. If not provided, a new one will be created"
  type        = string
  default     = null
}

variable "ecr_image_uri" {
  description = "ECR Image URI for the ECS task"
  type        = string
}