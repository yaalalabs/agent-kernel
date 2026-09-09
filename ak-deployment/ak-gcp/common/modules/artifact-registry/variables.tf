variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type        = string
  description = "GCP region"
  default     = "us-central1"
}

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

variable "source_path" {
  type        = string
  description = "Path to the Docker build context (relative to root module)"
}
