variable "project_id" {
  type        = string
  description = "GCP project to deploy into"
}

variable "region" {
  type        = string
  description = "Region of the agent-runner service"
}

variable "prefix" {
  type        = string
  description = "Name prefix: the service is <prefix>-runner"
}

variable "image_url" {
  type        = string
  description = "Container image the agent runner runs"
}

variable "command" {
  type        = list(string)
  description = "Container entrypoint override, e.g. [\"python\", \"-c\", \"from app import runner; runner()\"], where runner() calls CloudRunAgentRunner.run(). null keeps the image's"
  default     = null
}

variable "args" {
  type        = list(string)
  description = "Container arguments override. null keeps the image's"
  default     = null
}

variable "cpu" {
  type        = string
  description = "vCPUs per instance, e.g. 1 or 2"
  default     = "1"
}

variable "memory" {
  type        = string
  description = "Memory per instance, e.g. 512Mi or 2Gi"
  default     = "512Mi"
}

variable "min_instance_count" {
  type        = number
  description = "Instances kept running. 0 scales to zero between requests"
  default     = 0
}

variable "max_instance_count" {
  type        = number
  description = "Instances Cloud Run may scale up to"
  default     = 10
}

variable "concurrency" {
  type        = number
  description = "Requests (agent runs) one instance handles at once"
  default     = 5
}

variable "container_port" {
  type        = number
  description = "Port the agent runner listens on (the app's api.port)"
  default     = 8000
}

variable "environment_variables" {
  type        = map(string)
  description = "Environment for the agent runner, including the AK_EXECUTION__* queue coordinates"
  default     = {}
}

variable "vpc_connector_id" {
  type        = string
  description = "Serverless VPC Access connector the runner reaches Memorystore through"
}

variable "pubsub" {
  type = object({
    topics             = map(string)
    dead_letter_topics = map(string)
  })
  description = "The pubsub module's topic outputs: names keyed by queue (input, output)"
}

variable "grant_firestore" {
  type        = bool
  description = "Grant the runner Firestore access (sessions or threads on Firestore)"
  default     = false
}

variable "labels" {
  type        = map(string)
  description = "Labels applied to the service"
  default     = {}
}
