variable "region" {
  type        = string
  description = "Region"
  default     = "ap-southeast-2"
}

variable "product_alias" {
  type        = string
  description = "Product alias"
}

variable "env_alias" {
  type        = string
  description = "Environment alias"
}

variable "product_display_name" {
  type        = string
  description = "Product display name"
}

variable "api_root_path" {
  type        = string
  description = "Root API path"
  default     = var.env_alias
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

variable "tags" {
  type = map(string)
  description = "Resource tags"
  default = {}
}

