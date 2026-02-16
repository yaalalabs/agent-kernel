# Get current resource group
data "azurerm_resource_group" "current_group" {
  name = var.resource_group_name
}

data "azurerm_client_config" "current" {}

# Create Virtual Network (equivalent to VPC)
resource "azurerm_virtual_network" "main" {
  name                = "${var.product_alias}-${var.env_alias}-vnet"
  location            = data.azurerm_resource_group.current_group.location
  resource_group_name = data.azurerm_resource_group.current_group.name
  address_space       = [var.vnet_cidr]

  tags = merge(
    var.tags,
    {
      Name = "${var.product_alias}-${var.env_alias}-vnet"
    }
  )
}

# Create Public Subnets
resource "azurerm_subnet" "public" {
  count                = length(var.public_subnet_cidrs)
  name                 = "${var.product_alias}-${var.env_alias}-public-subnet-${count.index + 1}"
  resource_group_name  = data.azurerm_resource_group.current_group.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.public_subnet_cidrs[count.index]]
}

# Create Private Subnets
resource "azurerm_subnet" "private" {
  count                = length(var.private_subnet_cidrs)
  name                 = "${var.product_alias}-${var.env_alias}-private-subnet-${count.index + 1}"
  resource_group_name  = data.azurerm_resource_group.current_group.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.private_subnet_cidrs[count.index]]

  # Service endpoints ONLY for non-Flex subnets
  service_endpoints = count.index == 1 ? [] : [
    "Microsoft.Storage"
  ]

  # Delegation ONLY for Flex subnet (index 1)
  dynamic "delegation" {
    for_each = count.index == 1 ? [1] : []

    content {
      name = "flex-function-delegation"

      service_delegation {
        name = "Microsoft.App/environments"
        actions = [
          "Microsoft.Network/virtualNetworks/subnets/join/action"
        ]
      }
    }
  }
}


# Create Public IP for NAT Gateway
resource "azurerm_public_ip" "nat" {
  name                = "${var.product_alias}-${var.env_alias}-nat-pip"
  location            = data.azurerm_resource_group.current_group.location
  resource_group_name = data.azurerm_resource_group.current_group.name
  allocation_method   = "Static"
  sku                 = "Standard"

  tags = merge(
    var.tags,
    {
      Name = "${var.product_alias}-${var.env_alias}-nat-pip"
    }
  )
}

# Create NAT Gateway
resource "azurerm_nat_gateway" "nat" {
  name                = "${var.product_alias}-${var.env_alias}-nat"
  location            = data.azurerm_resource_group.current_group.location
  resource_group_name = data.azurerm_resource_group.current_group.name
  sku_name            = "Standard"

  tags = merge(
    var.tags,
    {
      Name = "${var.product_alias}-${var.env_alias}-nat"
    }
  )
}

# Associate Public IP with NAT Gateway
resource "azurerm_nat_gateway_public_ip_association" "nat" {
  nat_gateway_id       = azurerm_nat_gateway.nat.id
  public_ip_address_id = azurerm_public_ip.nat.id
}

# Associate NAT Gateway with Private Subnets
resource "azurerm_subnet_nat_gateway_association" "private" {
  count          = length(var.private_subnet_cidrs)
  subnet_id      = azurerm_subnet.private[count.index].id
  nat_gateway_id = azurerm_nat_gateway.nat.id
}