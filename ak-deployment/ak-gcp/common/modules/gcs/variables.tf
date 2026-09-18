variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type        = string
  description = "GCP region"
}

variable "prefix" {
  type        = string
  description = "Prefix applied to every resource name (e.g. \"myproduct-dev-agents\")"
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
