variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type        = string
  description = "GCP region"
}

variable "product_alias" {
  type        = string
  description = "Product alias"
}

variable "env_alias" {
  type        = string
  description = "Environment alias"
}

variable "is_production" {
  type        = bool
  description = "Whether this is a production environment"
  default     = false
}

variable "kms_key_id" {
  type        = string
  description = "Cloud KMS key for encryption (optional, uses Google-managed key if null)"
  default     = null
}

variable "labels" {
  type        = map(string)
  description = "Labels to apply to the bucket"
  default     = {}
}
