variable "region" {
  type        = string
  description = "Region"
}

variable "prefix" {
  type        = string
  description = "Prefix applied to every resource name"
}

variable "openai_api_key" {
  description = "OpenAI API Key"
  type        = string
}

variable "publisher_email" {
  type        = string
  description = "Publisher email for the API Management"
}
variable "resource_group_name" {
  type        = string
  description = "Resource group name"
}