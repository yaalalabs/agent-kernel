variable "product_alias" {
  description = "Product alias for naming resources"
  type        = string
}

variable "env_alias" {
  description = "Environment alias for naming resources"
  type        = string
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}
