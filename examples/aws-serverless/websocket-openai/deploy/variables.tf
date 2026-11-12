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

variable "openai_api_key" {
  description = "OpenAI API Key"
  type        = string
}
variable "demo_auth_token" {
  description = "The one credential the static identity provider in config.yaml accepts on the WebSocket $connect handshake"
  type        = string
  sensitive   = true
}
