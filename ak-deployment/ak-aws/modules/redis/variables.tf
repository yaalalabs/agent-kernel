variable "product_alias" {
  type        = string
  description = "Product alias"
}

variable "env_alias" {
  type        = string
  description = "Environment alias"
}

variable "module_name" {
  type        = string
  description = "Module name"
}

variable "tags" {
  type = map(string)
  description = "Resource tags"
  default = {}
}

variable "vpc_cidr" {
  type        = string
  description = "CIDR block for the VPC"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID"
}

variable "subnet_ids" {
  type = list(string)
  description = "When using an existing VPC to deploy, private subnet IDs need to be provided"
}

variable "node_type" {
  type        = string
  description = "Redis node type"
  default     = "cache.t3.micro"
}

variable node_count {
  type        = number
  description = "Number of Redis nodes"
  default     = 1
}

variable port {
  type        = number
  description = "Redis port"
  default     = 6379
}