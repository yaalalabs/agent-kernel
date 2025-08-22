output "vpc_id" {
  description = "The ID of the VPC"
  value       = local.existing_vpc_id != null ? local.existing_vpc_id : try(aws_vpc.main[0].id, "")
}

output "public_subnet_ids" {
  description = "List of IDs of public subnets"
  value       = local.existing_vpc_id != null ? try(data.aws_subnets.existing_public[0].ids, []) : aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "List of IDs of private subnets"
  value       = local.existing_vpc_id != null ? try(data.aws_subnets.existing_private[0].ids, []) : aws_subnet.private[*].id
}

output "nat_gateway_id" {
  description = "ID of the NAT Gateway"
  value       = local.existing_nat_id != null ? local.existing_nat_id : try(aws_nat_gateway.nat[0].id, "")
}

output "internet_gateway_id" {
  description = "ID of the Internet Gateway"
  value       = local.existing_igw_id != null ? local.existing_igw_id : try(aws_internet_gateway.igw[0].id, "")
}

output "public_route_table_id" {
  description = "ID of the public route table"
  value       = local.existing_public_rt_id != null ? local.existing_public_rt_id : try(aws_route_table.public[0].id, "")
}

output "private_route_table_id" {
  description = "ID of the private route table"
  value       = local.existing_private_rt_id != null ? local.existing_private_rt_id : try(aws_route_table.private[0].id, "")
}