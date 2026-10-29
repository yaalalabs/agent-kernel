variable "region" {
  description = "AWS region"
  type        = string
}

variable "prefix" {
  description = "Prefix applied to every security group name"
  type        = string
  default     = "ak-ci-containerized-shared"
}

variable "vpc_id" {
  description = "VPC ID of the weekly base deployment (examples/aws-serverless/openai)"
  type        = string
}

variable "container_port" {
  description = "REST service container port the ECS service security group accepts from the ALB. Must match rest_service.container_port of every aws-containerized example in the weekly matrix."
  type        = number
  default     = 8000
}
