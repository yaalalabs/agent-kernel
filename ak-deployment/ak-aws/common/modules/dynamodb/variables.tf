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
  description = "Module name (logical component name)"
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}

variable "table_name" {
  type        = string
  description = "Explicit DynamoDB table name. If null, a name is constructed from product/env/module."
}

variable "attributes" {
  description = "List of attribute definitions for the table and indexes"
  type = list(object({
    name = string
    type = string
  }))
}

variable "hash_key" {
  type        = string
  description = "Partition key attribute name"
}

variable "range_key" {
  type        = string
  description = "Sort key attribute name (optional)"
  default     = null
}

# Capacity & billing
variable "billing_mode" {
  type        = string
  description = "Billing mode for the table: PROVISIONED or PAY_PER_REQUEST"
  default     = "PAY_PER_REQUEST"
}

variable "read_capacity" {
  type        = number
  description = "Read capacity units (only when PROVISIONED)"
  default     = null
}

variable "write_capacity" {
  type        = number
  description = "Write capacity units (only when PROVISIONED)"
  default     = null
}

# Indexes
variable "global_secondary_indexes" {
  description = "Definition of Global Secondary Indexes"
  type = list(object({
    name               = string
    hash_key           = string
    range_key          = optional(string)
    projection_type    = string
    non_key_attributes = optional(list(string))
    read_capacity      = optional(number)
    write_capacity     = optional(number)
  }))
  default = []
}

variable "local_secondary_indexes" {
  description = "Definition of Local Secondary Indexes"
  type = list(object({
    name               = string
    range_key          = string
    projection_type    = string
    non_key_attributes = optional(list(string))
  }))
  default = []
}

variable "ttl_enabled" {
  type        = bool
  description = "Whether TTL is enabled"
  default     = false
}

variable "ttl_attribute_name" {
  type        = string
  description = "TTL attribute name when TTL is enabled"
  default     = null
}

variable "stream_enabled" {
  type        = bool
  description = "Whether DynamoDB streams are enabled"
  default     = false
}

variable "stream_view_type" {
  type        = string
  description = "When streams are enabled, the view type: NEW_IMAGE | OLD_IMAGE | NEW_AND_OLD_IMAGES | KEYS_ONLY"
  default     = null
}

variable "point_in_time_recovery_enabled" {
  type        = bool
  description = "Enable Point-in-Time Recovery"
  default     = true
}

variable "server_side_encryption_enabled" {
  type        = bool
  description = "Enable server-side encryption"
  default     = true
}

variable "kms_key_arn" {
  type        = string
  description = "KMS key ARN for SSE (optional; if null, AWS owned key is used)"
  default     = null
}

variable "deletion_protection_enabled" {
  type        = bool
  description = "Enable deletion protection on the table"
  default     = false
}
