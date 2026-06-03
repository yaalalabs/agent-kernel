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

variable "public_subnet_cidr" {
  type        = string
  description = "CIDR range for the public subnet"
  default     = "10.0.1.0/24"
}

variable "private_subnet_cidr" {
  type        = string
  description = "CIDR range for the private subnet"
  default     = "10.0.2.0/24"
}

variable "tags" {
  type        = map(string)
  description = "Resource labels"
  default     = {}
}
