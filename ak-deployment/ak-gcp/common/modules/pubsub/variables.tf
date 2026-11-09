variable "project_id" {
  type        = string
  description = "GCP project that owns the topics and subscriptions"
}

variable "prefix" {
  type        = string
  description = "Name prefix: the queues are <prefix>-agent-input and <prefix>-agent-output"
}

variable "input_queue_max_receive_count" {
  type        = number
  description = "Deliveries of a request before it is permanently failed. The agent runner fails it on this delivery; the subscription's dead-letter policy is the backstop, clamped to Pub/Sub's 5-100 range"
  default     = 3
}

variable "output_queue_max_receive_count" {
  type        = number
  description = "Deliveries of a reply before it is permanently failed (see input_queue_max_receive_count)"
  default     = 3
}

variable "input_push_endpoint" {
  type        = string
  description = "URL the request subscription pushes to: the agent runner's push route"
}

variable "input_push_service_account_email" {
  type        = string
  description = "Identity Pub/Sub signs each push with (an OIDC token the agent runner's service checks)"
}

variable "dlq_suffix" {
  type        = string
  description = "Suffix appended to a queue topic's name for its dead-letter topic"
  default     = "-dlq"
}

variable "labels" {
  type        = map(string)
  description = "Labels applied to the topics and subscriptions"
  default     = {}
}
