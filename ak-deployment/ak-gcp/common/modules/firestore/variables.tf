variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type        = string
  description = "GCP region"
  default     = "us-central1"
}

variable "prefix" {
  type        = string
  description = "Prefix applied to every resource name (e.g. \"myproduct-dev-agents\")"
}

variable "collection_name" {
  type        = string
  description = "Firestore collection name for session data"
  default     = "sessions"
}

variable "ttl_field" {
  type        = string
  description = "Field name used for TTL expiration"
  default     = "expiry_time"
}

variable "deletion_protection" {
  type        = bool
  description = "Enable deletion protection on the database"
  default     = false
}

variable "point_in_time_recovery" {
  type        = bool
  description = "Enable point-in-time recovery"
  default     = false
}
