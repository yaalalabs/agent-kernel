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

variable "source_path" {
  type        = string
  description = "Path to the Docker build context (relative to root module)"
}
