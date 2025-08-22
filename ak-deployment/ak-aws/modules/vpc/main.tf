# Get available AZs in the region
data "aws_availability_zones" "available" {
  state = "available"
}

# Look up existing VPC by name tag
data "aws_vpcs" "existing" {
  filter {
    name   = "tag:Name"
    values = ["${var.product_alias}-${var.env_alias}-vpc"]
  }
}

# Get the first VPC ID if any exist
locals {
  existing_vpc_id = length(data.aws_vpcs.existing.ids) > 0 ? tolist(data.aws_vpcs.existing.ids)[0] : null
}

# Get details of the existing VPC if it exists
data "aws_vpc" "existing" {
  count = local.existing_vpc_id != null ? 1 : 0
  id    = local.existing_vpc_id
}

# Create a new VPC only if one doesn't exist
resource "aws_vpc" "main" {
  count               = local.existing_vpc_id == null ? 1 : 0
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "${var.product_alias}-${var.env_alias}-vpc"
  }
}

# Look up existing public subnets if VPC exists
data "aws_subnets" "existing_public" {
  count = local.existing_vpc_id != null ? 1 : 0
  filter {
    name   = "vpc-id"
    values = [local.existing_vpc_id]
  }
  filter {
    name   = "tag:Name"
    values = ["${var.product_alias}-${var.env_alias}-public-subnet-*"]
  }
}

# Look up existing private subnets if VPC exists
data "aws_subnets" "existing_private" {
  count = local.existing_vpc_id != null ? 1 : 0
  filter {
    name   = "vpc-id"
    values = [local.existing_vpc_id]
  }
  filter {
    name   = "tag:Name"
    values = ["${var.product_alias}-${var.env_alias}-private-subnet-*"]
  }
}

# Create public subnets (for NAT Gateway) only if VPC doesn't exist
resource "aws_subnet" "public" {
  count                   = local.existing_vpc_id == null ? length(var.public_subnet_cidrs) : 0
  vpc_id                  = aws_vpc.main[0].id
  cidr_block              = var.public_subnet_cidrs[count.index]
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "${var.product_alias}-${var.env_alias}-public-subnet-${count.index + 1}"
  }
}

# Create private subnets (for Lambda) only if VPC doesn't exist
resource "aws_subnet" "private" {
  count             = local.existing_vpc_id == null ? length(var.private_subnet_cidrs) : 0
  vpc_id            = aws_vpc.main[0].id
  cidr_block        = var.private_subnet_cidrs[count.index]
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = {
    Name = "${var.product_alias}-${var.env_alias}-private-subnet-${count.index + 1}"
  }
}

# Look up existing Internet Gateway if VPC exists
data "aws_internet_gateway" "existing" {
  count = local.existing_vpc_id != null ? 1 : 0
  filter {
    name   = "attachment.vpc-id"
    values = [local.existing_vpc_id]
  }
}

locals {
  existing_igw_id = local.existing_vpc_id != null ? try(data.aws_internet_gateway.existing[0].id, null) : null
}

# Create Internet Gateway only if VPC doesn't exist
resource "aws_internet_gateway" "igw" {
  count  = local.existing_vpc_id == null ? 1 : 0
  vpc_id = aws_vpc.main[0].id

  tags = {
    Name = "${var.product_alias}-${var.env_alias}-igw"
  }
}

# Look up existing NAT Gateway if VPC exists
data "aws_nat_gateways" "existing" {
  count = local.existing_vpc_id != null ? 1 : 0
  filter {
    name   = "vpc-id"
    values = [local.existing_vpc_id]
  }
  filter {
    name   = "tag:Name"
    values = ["${var.product_alias}-${var.env_alias}-nat"]
  }
}

locals {
  existing_nat_id = local.existing_vpc_id != null && length(try(data.aws_nat_gateways.existing[0].ids, [])) > 0 ? tolist(data.aws_nat_gateways.existing[0].ids)[0] : null
}

# Create Elastic IP for NAT Gateway only if VPC doesn't exist
resource "aws_eip" "nat" {
  count  = local.existing_vpc_id == null ? 1 : 0
  domain = "vpc"

  tags = {
    Name = "${var.product_alias}-${var.env_alias}-nat-eip"
  }
}

# Create NAT Gateway only if VPC doesn't exist
resource "aws_nat_gateway" "nat" {
  count         = local.existing_vpc_id == null ? 1 : 0
  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public[0].id

  tags = {
    Name = "${var.product_alias}-${var.env_alias}-nat"
  }
  depends_on = [aws_internet_gateway.igw]
}

# Look up existing route tables if VPC exists
data "aws_route_tables" "existing_public" {
  count = local.existing_vpc_id != null ? 1 : 0
  vpc_id = local.existing_vpc_id
  filter {
    name   = "tag:Name"
    values = ["${var.product_alias}-${var.env_alias}-public-route-table"]
  }
}

data "aws_route_tables" "existing_private" {
  count = local.existing_vpc_id != null ? 1 : 0
  vpc_id = local.existing_vpc_id
  filter {
    name   = "tag:Name"
    values = ["${var.product_alias}-${var.env_alias}-private-route-table"]
  }
}

locals {
  existing_public_rt_id = local.existing_vpc_id != null && length(try(data.aws_route_tables.existing_public[0].ids, [])) > 0 ? tolist(data.aws_route_tables.existing_public[0].ids)[0] : null
  existing_private_rt_id = local.existing_vpc_id != null && length(try(data.aws_route_tables.existing_private[0].ids, [])) > 0 ? tolist(data.aws_route_tables.existing_private[0].ids)[0] : null
}

# Create route table for public subnets only if VPC doesn't exist
resource "aws_route_table" "public" {
  count  = local.existing_vpc_id == null ? 1 : 0
  vpc_id = aws_vpc.main[0].id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.igw[0].id
  }

  tags = {
    Name = "${var.product_alias}-${var.env_alias}-public-route-table"
  }
}

# Create route table for private subnets only if VPC doesn't exist
resource "aws_route_table" "private" {
  count  = local.existing_vpc_id == null ? 1 : 0
  vpc_id = aws_vpc.main[0].id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.nat[0].id
  }

  tags = {
    Name = "${var.product_alias}-${var.env_alias}-private-route-table"
  }
}

# Associate public subnets with public route table only if VPC doesn't exist
resource "aws_route_table_association" "public" {
  count          = local.existing_vpc_id == null ? length(var.public_subnet_cidrs) : 0
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public[0].id
}

# Associate private subnets with private route table only if VPC doesn't exist
resource "aws_route_table_association" "private" {
  count          = local.existing_vpc_id == null ? length(var.private_subnet_cidrs) : 0
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[0].id
}