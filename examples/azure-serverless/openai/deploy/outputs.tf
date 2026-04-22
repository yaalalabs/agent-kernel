output "function_app_url" {
  description = "Function App default hostname"
  value       = module.FlexFunction.function_app_url
}

output "function_app_id" {
  description = "Function App resource ID"
  value       = module.FlexFunction.function_app_id
}

output "function_app_name" {
  description = "Function App name"
  value       = module.FlexFunction.function_app_name
}

output "api_management_gateway_url" {
  description = "API Management gateway URL"
  value       = module.FlexFunction.api_management_gateway_url
}

output "api_url"{
  description = "Complete API URL with base path and version"
  value       = module.FlexFunction.api_url
}

output "agent_invoke_url" {
  description = "Complete Agent Invoke URL"
  value       = "${module.FlexFunction.api_url}/chat"
}

output "vnet_id" {
  description = "ID of the Virtual Network"
  value       = module.FlexFunction.vnet_id
  
}

output "subnet_ids" {
  description = "IDs of the subnets"
  value       = module.FlexFunction.private_subnet_ids
}