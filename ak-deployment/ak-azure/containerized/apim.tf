# API Management Service
resource "azurerm_api_management" "apim" {
  name                = "${var.product_alias}-${var.env_alias}-apim"
  location            = var.region
  resource_group_name = data.azurerm_resource_group.rg.name
  publisher_name      = var.publisher_name
  publisher_email     = var.publisher_email
  sku_name            = "Developer_1"

  identity {
    type = "SystemAssigned"
  }
  virtual_network_configuration {
    subnet_id = local.subnet_ids
  }
  virtual_network_type = "External"
  tags = var.tags

  depends_on = [ azurerm_subnet_network_security_group_association.shared_subnet_nsg_assoc ]

}

# Create Private DNS Zone for Container Apps
resource "azurerm_private_dns_zone" "containerapp" {
  name                = azurerm_container_app_environment.env.default_domain
  resource_group_name = data.azurerm_resource_group.rg.name
  
  tags = var.tags

  depends_on = [azurerm_container_app_environment.env]
}

# Link the Private DNS zone to the VNet where APIM resides
resource "azurerm_private_dns_zone_virtual_network_link" "apim_to_containerapp" {
  name                  = "${var.product_alias}-${var.env_alias}-apim-containerapp-dns-link"
  resource_group_name   = data.azurerm_resource_group.rg.name
  private_dns_zone_name = azurerm_private_dns_zone.containerapp.name
  virtual_network_id    = local.vnet_id
  registration_enabled  = false
  
  depends_on = [
    azurerm_private_dns_zone.containerapp,
    azurerm_api_management.apim
  ]
}

# Create DNS A record for the Container App
resource "azurerm_private_dns_a_record" "containerapp" {
  name                = azurerm_container_app.app.name
  zone_name           = azurerm_private_dns_zone.containerapp.name
  resource_group_name = data.azurerm_resource_group.rg.name
  ttl                 = 300
  records             = [azurerm_container_app_environment.env.static_ip_address]
  
  tags = var.tags

  depends_on = [
    azurerm_private_dns_zone.containerapp,
    azurerm_container_app.app
  ]
}

# Create wildcard DNS record for Container App revisions
resource "azurerm_private_dns_a_record" "containerapp_wildcard" {
  name                = "*.${azurerm_container_app.app.name}"
  zone_name           = azurerm_private_dns_zone.containerapp.name
  resource_group_name = data.azurerm_resource_group.rg.name
  ttl                 = 300
  records             = [azurerm_container_app_environment.env.static_ip_address]
  
  tags = var.tags

  depends_on = [
    azurerm_private_dns_zone.containerapp,
    azurerm_container_app.app
  ]
}

# Update the backend dependency
resource "azurerm_api_management_backend" "container_backend" {
  name                = "${var.product_alias}-${var.env_alias}-container-backend"
  resource_group_name = data.azurerm_resource_group.rg.name
  api_management_name = azurerm_api_management.apim.name
  protocol            = "http"
  url                 = "https://${azurerm_container_app.app.ingress[0].fqdn}"
  description         = "Backend for Container App"

  depends_on = [
    azurerm_container_app.app,
    azurerm_private_dns_zone_virtual_network_link.apim_to_containerapp,
    azurerm_private_dns_a_record.containerapp
  ]
}


# API within API Management
resource "azurerm_api_management_api" "rest_api" {
  name                = "${var.product_alias}-${var.env_alias}-rest-api"
  resource_group_name = data.azurerm_resource_group.rg.name
  api_management_name = azurerm_api_management.apim.name
  revision            = "1"
  display_name        = "[${var.env_alias}] ${var.product_display_name} REST API"
  path                = var.api_base_path != null && var.api_base_path != "" ? var.api_base_path : ""
  protocols           = ["https"]

  subscription_required = false

}

# API Version Set
resource "azurerm_api_management_api_version_set" "version_set" {
  name                = "${var.product_alias}-${var.env_alias}-version-set"
  resource_group_name = data.azurerm_resource_group.rg.name
  api_management_name = azurerm_api_management.apim.name
  display_name        = "API Versions"
  versioning_scheme   = "Segment"

  depends_on = [azurerm_api_management_api.rest_api]
}

# Local variables for processing endpoints
locals {
  # Default endpoints
  default_endpoint_path = "/${join("/", compact([local.api_base_segment, var.api_version, var.agent_endpoint]))}"
  default_gateway_endpoint = {
    path           = local.default_endpoint_path
    method         = "POST"
    overwrite_path = "/run"
  }

  multipart_endpoint_path = "/${join("/", compact([local.api_base_segment, var.api_version, "${var.agent_endpoint}-multipart"]))}"
  multipart_gateway_endpoint = {
    path           = local.multipart_endpoint_path
    method         = "POST"
    overwrite_path = "/run-multipart"
  }

  # Create default gateway map
  default_gateway_map = {
    "POST ${local.default_endpoint_path}"    = local.default_gateway_endpoint
    "POST ${local.multipart_endpoint_path}" = local.multipart_gateway_endpoint
  }

  # User-defined gateway endpoints
  user_gateway_map = {
    for ep in var.gateway_endpoints :
    "${upper(try(ep["method"], "POST"))} /${join("/", compact([local.api_base_segment, var.api_version, trim(try(ep["path"], ""), "/")]))}" => {
      path           = "/${join("/", compact([local.api_base_segment, var.api_version, trim(try(ep["path"], ""), "/")]))}"
      method         = upper(try(ep["method"], "POST"))
      overwrite_path = try(ep["overwrite_path"], "/${trim(try(ep["path"], ""), "/")}")
    }
  }

  # Merge default and user endpoints
  gateway_endpoints_map = merge(local.default_gateway_map, local.user_gateway_map)

  # Create endpoint map for APIM operations
  endpoint_map = {
    for key, ep in local.gateway_endpoints_map :
    replace(key, "/", "-") => {
      method         = ep.method
      full_path      = trimprefix(ep.path, "/")
      relative_path  = var.api_base_path != null && var.api_base_path != "" ? trimprefix(trimprefix(ep.path, "/"), "${var.api_base_path}/") : trimprefix(ep.path, "/")
      overwrite_path = ep.overwrite_path
    }
  }
}


# Use the same map for both resources
resource "azurerm_api_management_api_operation" "operations" {
  for_each = local.endpoint_map

  operation_id = substr(
    replace(
      replace(
        replace(lower(each.key), " ", "_"),
        "/", "_"
      ),
      "__", "_"
    ),
    0,
    80
  )

  display_name = each.key
  method       = each.value.method
  url_template = each.value.relative_path
  api_name            = azurerm_api_management_api.rest_api.name
  api_management_name = azurerm_api_management.apim.name
  resource_group_name = data.azurerm_resource_group.rg.name

  response {
    status_code = 200
    description = "Success"
  }
}

# Policy to route each operation to the Container App
resource "azurerm_api_management_api_operation_policy" "operation_policy" {
  for_each = local.endpoint_map

  api_name            = azurerm_api_management_api.rest_api.name
  api_management_name = azurerm_api_management.apim.name
  resource_group_name = data.azurerm_resource_group.rg.name
  operation_id        = azurerm_api_management_api_operation.operations[each.key].operation_id

  xml_content = <<XML
<policies>
  <inbound>
    <base />
    <set-backend-service backend-id="${azurerm_api_management_backend.container_backend.name}" />
    <rewrite-uri template="${each.value.overwrite_path}" />
  </inbound>
  <backend>
    <base />
  </backend>
  <outbound>
    <base />
  </outbound>
  <on-error>
    <base />
  </on-error>
</policies>
XML

  depends_on = [
    azurerm_api_management_backend.container_backend,
    azurerm_api_management_api_operation.operations,
    azurerm_subnet_network_security_group_association.shared_subnet_nsg_assoc
  ]
}

# Diagnostic settings for API Management
resource "azurerm_api_management_logger" "apim_logger" {
  name                = "${var.product_alias}-${var.env_alias}-apim-logger"
  api_management_name = azurerm_api_management.apim.name
  resource_group_name = data.azurerm_resource_group.rg.name
  resource_id         = azurerm_application_insights.container_insights.id

  application_insights {
    instrumentation_key = azurerm_application_insights.container_insights.instrumentation_key
  }

  depends_on = [azurerm_application_insights.container_insights]
}

resource "azurerm_api_management_api_diagnostic" "api_diagnostic" {
  identifier               = "applicationinsights"
  resource_group_name      = data.azurerm_resource_group.rg.name
  api_management_name      = azurerm_api_management.apim.name
  api_name                 = azurerm_api_management_api.rest_api.name
  api_management_logger_id = azurerm_api_management_logger.apim_logger.id

  sampling_percentage       = 100.0
  always_log_errors         = true
  log_client_ip             = true
  verbosity                 = "information"
  http_correlation_protocol = "W3C"

  frontend_request {
    body_bytes = 1024
    headers_to_log = [
      "content-type",
      "accept",
      "origin"
    ]
  }

  frontend_response {
    body_bytes = 1024
    headers_to_log = [
      "content-type",
      "content-length"
    ]
  }

  backend_request {
    body_bytes = 1024
    headers_to_log = [
      "content-type"
    ]
  }

  backend_response {
    body_bytes = 1024
    headers_to_log = [
      "content-type",
      "content-length"
    ]
  }

  depends_on = [azurerm_api_management_logger.apim_logger]
}

resource "azurerm_network_security_group" "shared_nsg" {
  name                = "${var.product_alias}-${var.env_alias}-nsg"
  location            = var.region
  resource_group_name = data.azurerm_resource_group.rg.name

  tags = var.tags
}

# Allow all traffic FROM VirtualNetwork (internal subnet-to-subnet communication)
resource "azurerm_network_security_rule" "allow_vnet_inbound" {
  name                        = "AllowVNetInbound"
  priority                    = 100
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "*"
  source_port_range           = "*"
  destination_port_range      = "*"
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "VirtualNetwork"
  resource_group_name         = data.azurerm_resource_group.rg.name
  network_security_group_name = azurerm_network_security_group.shared_nsg.name
}

# APIM Management from ApiManagement service tag (required for APIM)
resource "azurerm_network_security_rule" "apim_management" {
  name                        = "AllowAPIMManagement"
  priority                    = 110
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "3443"
  source_address_prefix       = "ApiManagement"
  destination_address_prefix  = "VirtualNetwork"
  resource_group_name         = data.azurerm_resource_group.rg.name
  network_security_group_name = azurerm_network_security_group.shared_nsg.name
}

# Allow HTTPS from Internet (for APIM External access)
resource "azurerm_network_security_rule" "allow_https_internet" {
  name                        = "AllowHTTPSFromInternet"
  priority                    = 120
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "443"
  source_address_prefix       = "Internet"
  destination_address_prefix  = "VirtualNetwork"
  resource_group_name         = data.azurerm_resource_group.rg.name
  network_security_group_name = azurerm_network_security_group.shared_nsg.name
}

# Allow HTTP from Internet (for APIM External access - optional)
resource "azurerm_network_security_rule" "allow_http_internet" {
  name                        = "AllowHTTPFromInternet"
  priority                    = 130
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "80"
  source_address_prefix       = "Internet"
  destination_address_prefix  = "VirtualNetwork"
  resource_group_name         = data.azurerm_resource_group.rg.name
  network_security_group_name = azurerm_network_security_group.shared_nsg.name
}

# Allow all outbound to VirtualNetwork (internal communication)
resource "azurerm_network_security_rule" "allow_vnet_outbound" {
  name                        = "AllowVNetOutbound"
  priority                    = 100
  direction                   = "Outbound"
  access                      = "Allow"
  protocol                    = "*"
  source_port_range           = "*"
  destination_port_range      = "*"
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "VirtualNetwork"
  resource_group_name         = data.azurerm_resource_group.rg.name
  network_security_group_name = azurerm_network_security_group.shared_nsg.name
}

# APIM Outbound - Storage (required)
resource "azurerm_network_security_rule" "apim_outbound_storage" {
  name                        = "AllowStorage"
  priority                    = 110
  direction                   = "Outbound"
  access                      = "Allow"
  protocol                    = "*"
  source_port_range           = "*"
  destination_port_range      = "443"
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "Storage"
  resource_group_name         = data.azurerm_resource_group.rg.name
  network_security_group_name = azurerm_network_security_group.shared_nsg.name
}

# APIM Outbound - SQL (required)
resource "azurerm_network_security_rule" "apim_outbound_sql" {
  name                        = "AllowSQL"
  priority                    = 120
  direction                   = "Outbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "1433"
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "Sql"
  resource_group_name         = data.azurerm_resource_group.rg.name
  network_security_group_name = azurerm_network_security_group.shared_nsg.name
}

# APIM Outbound - Azure Monitor (required)
resource "azurerm_network_security_rule" "apim_outbound_monitor" {
  name                        = "AllowAzureMonitor"
  priority                    = 130
  direction                   = "Outbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_ranges     = ["443", "1886"]
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "AzureMonitor"
  resource_group_name         = data.azurerm_resource_group.rg.name
  network_security_group_name = azurerm_network_security_group.shared_nsg.name
}

# Allow Internet outbound (for APIM to call external APIs if needed)
resource "azurerm_network_security_rule" "allow_internet_outbound" {
  name                        = "AllowInternetOutbound"
  priority                    = 140
  direction                   = "Outbound"
  access                      = "Allow"
  protocol                    = "*"
  source_port_range           = "*"
  destination_port_range      = "*"
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "Internet"
  resource_group_name         = data.azurerm_resource_group.rg.name
  network_security_group_name = azurerm_network_security_group.shared_nsg.name
}

# Associate NSG with the shared subnet
resource "azurerm_subnet_network_security_group_association" "shared_subnet_nsg_assoc" {
  subnet_id                 = local.subnet_ids
  network_security_group_id = azurerm_network_security_group.shared_nsg.id

  depends_on = [ azurerm_network_security_rule.allow_http_internet, azurerm_network_security_rule.allow_https_internet, azurerm_network_security_rule.allow_internet_outbound, azurerm_network_security_rule.allow_vnet_inbound, azurerm_network_security_rule.allow_vnet_outbound, azurerm_network_security_rule.apim_management, azurerm_network_security_rule.apim_outbound_monitor, azurerm_network_security_rule.apim_outbound_sql, azurerm_network_security_rule.apim_outbound_storage,  ]

}