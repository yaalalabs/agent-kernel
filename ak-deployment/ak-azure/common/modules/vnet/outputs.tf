output "vnet_id" {
  description = "The ID of the Virtual Network"
  value       = azurerm_virtual_network.main.id
}

output "vnet_name" {
  description = "The name of the Virtual Network"
  value       = azurerm_virtual_network.main.name
}

output "public_subnet_ids" {
  description = "List of IDs of public subnets"
  value       = azurerm_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "List of IDs of private subnets"
  value       = azurerm_subnet.private[*].id
}

output "private_subnet_name" {
  description = "Name of the private subnet"
  value       = azurerm_subnet.private[0].name
}

output "function_subnet_name" {
  description = "Name of the function subnet"
  value       = azurerm_subnet.private[1].name
}

output "nat_gateway_id" {
  description = "ID of the NAT Gateway"
  value       = azurerm_nat_gateway.nat.id
}

output "nat_public_ip_id" {
  description = "ID of the NAT Gateway Public IP"
  value       = azurerm_public_ip.nat.id
}

output "nat_public_ip_address" {
  description = "Public IP address of the NAT Gateway"
  value       = azurerm_public_ip.nat.ip_address
}
