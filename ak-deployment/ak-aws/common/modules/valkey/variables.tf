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
  type        = map(string)
  description = "Resource tags"
  default     = {}
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
  type        = list(string)
  description = "When using an existing VPC to deploy, private subnet IDs need to be provided"
}

variable "node_type" {
  type        = string
  description = "Valkey node type"
  default     = "cache.t4g.micro"
}

variable "node_count" {
  type        = number
  description = "Number of Valkey nodes"
  default     = 1
}

variable "port" {
  type        = number
  description = "Valkey port"
  default     = 6379
}

variable "engine_version" {
  type        = string
  description = "Valkey engine version. Must match the parameter_group_name family (e.g. 8.0 -> default.valkey8)"
  default     = "8.0"
}

variable "parameter_group_name" {
  type        = string
  description = "ElastiCache parameter group name. Its family must match the engine major version (e.g. default.valkey8 for engine_version 8.x)"
  default     = "default.valkey8"
}
