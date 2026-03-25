# WebSocket Connections Table Module Variables

variable "product_alias" {
  type        = string
  description = "Product alias for resource naming"
}

variable "env_alias" {
  type        = string
  description = "Environment alias for resource naming"
}

variable "tags" {
  type        = map(string)
  description = "Tags to apply to resources"
  default     = {}
}

variable "table_name" {
  type        = string
  description = "DynamoDB table name for WebSocket connections"
  default     = "websocket-connections"
}

variable "billing_mode" {
  type        = string
  description = "DynamoDB billing mode"
  default     = "PAY_PER_REQUEST"
  validation {
    condition     = contains(["PAY_PER_REQUEST", "PROVISIONED"], var.billing_mode)
    error_message = "Billing mode must be either PAY_PER_REQUEST or PROVISIONED."
  }
}

variable "hash_key" {
  type        = string
  description = "Hash key for the DynamoDB table"
  default     = "session_id"
}

variable "range_key" {
  type        = string
  description = "Range key for the DynamoDB table"
  default     = "connection_id"
}

variable "gsi_name" {
  type        = string
  description = "Name of the Global Secondary Index"
  default     = "connection_id-index"
}

variable "gsi_hash_key" {
  type        = string
  description = "Hash key for the Global Secondary Index"
  default     = "connection_id"
}

variable "gsi_projection_type" {
  type        = string
  description = "Projection type for the Global Secondary Index"
  default     = "ALL"
  validation {
    condition     = contains(["ALL", "KEYS_ONLY", "INCLUDE"], var.gsi_projection_type)
    error_message = "GSI projection type must be one of: ALL, KEYS_ONLY, INCLUDE."
  }
}

variable "ttl_attribute_name" {
  type        = string
  description = "TTL attribute name for automatic cleanup"
  default     = "ttl"
}

variable "ttl_enabled" {
  type        = bool
  description = "Enable TTL for automatic cleanup of stale connections"
  default     = true
}