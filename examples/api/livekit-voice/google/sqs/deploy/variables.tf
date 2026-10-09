variable "region" {
  type        = string
  description = "Region"
}

variable "prefix" {
  type        = string
  description = "Prefix applied to every resource name"
}

variable "is_production" {
  description = "Is production"
  type        = bool
  default     = false
}

variable "GOOGLE_API_KEY" {
  description = "Google API Key"
  type        = string
}

variable "livekit_url" {
  description = "LiveKit URL"
  type        = string
}

variable "livekit_api_key" {
  description = "LiveKit API Key"
  type        = string
}

variable "livekit_api_secret" {
  description = "LiveKit API Secret"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID for ECS deployment"
  type        = string
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for ECS deployment"
  type        = list(string)
}
