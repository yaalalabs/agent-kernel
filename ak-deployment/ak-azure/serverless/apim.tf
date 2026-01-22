# API Management Service
resource "azurerm_api_management" "apim" {
  name                = "${var.product_alias}-${var.env_alias}-apim"
  location            = var.region
  resource_group_name = data.azurerm_resource_group.rg.name
  publisher_name      = var.publisher_name
  publisher_email     = var.publisher_email
  sku_name            = var.apim_sku_name

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags
}

resource "time_sleep" "wait_for_apim" {
  depends_on      = [azurerm_api_management.apim]
  create_duration = "5m"
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

  depends_on = [time_sleep.wait_for_apim]
}

# API Version Set
resource "azurerm_api_management_api_version_set" "version_set" {
  name                = "${var.product_alias}-${var.env_alias}-version-set"
  resource_group_name = data.azurerm_resource_group.rg.name
  api_management_name = azurerm_api_management.apim.name
  display_name        = "API Versions"
  versioning_scheme   = "Segment"
}

# Local variables for processing endpoints
locals {
  # Parse endpoints into components
  parsed_endpoints = [
    for ep in var.gateway_endpoints : {
      function_name = ep.function_name
      method        = upper(ep.method)
      full_path     = trimprefix(ep.path, "/")
    }
  ]

  # Create endpoint map with unique keys
  endpoint_map = {
    for idx, ep in local.parsed_endpoints :
    "${ep.function_name}-${ep.method}-${replace(ep.full_path, "/", "-")}" => ep
  }
}

# Get Function App host keys
data "azurerm_function_app_host_keys" "function_keys" {
  name                = azurerm_function_app_flex_consumption.function.name
  resource_group_name = azurerm_function_app_flex_consumption.function.resource_group_name
  
  depends_on = [azurerm_function_app_flex_consumption.function, null_resource.deploy_function_code]
}

# Backend for Function App (single backend for all functions)
resource "azurerm_api_management_backend" "function_backend" {
  name                = "${var.product_alias}-${var.env_alias}-function-backend"
  resource_group_name = data.azurerm_resource_group.rg.name
  api_management_name = azurerm_api_management.apim.name
  protocol            = "http"
  url                 = "https://${azurerm_function_app_flex_consumption.function.default_hostname}/api"

  credentials {
    header = {
      "x-functions-key" = data.azurerm_function_app_host_keys.function_keys.default_function_key
    }
  }
}

# Create API Operations for each endpoint
resource "azurerm_api_management_api_operation" "operations" {
  for_each = local.endpoint_map

  operation_id        = each.key
  api_name            = azurerm_api_management_api.rest_api.name
  api_management_name = azurerm_api_management.apim.name
  resource_group_name = data.azurerm_resource_group.rg.name
  display_name        = "${each.value.method} ${each.value.full_path} (${each.value.function_name})"
  method              = each.value.method
  url_template        = "/${var.api_version}/${each.value.full_path}"
  description         = "Endpoint for ${each.value.method} ${each.value.full_path} routed to function ${each.value.function_name}"

  response {
    status_code = 200
    description = "Success"
  }
}

# Policy to route each operation to the appropriate function
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
    <set-backend-service backend-id="${azurerm_api_management_backend.function_backend.name}" />
    <rewrite-uri template="/${each.value.function_name}" />
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
}

# Diagnostic settings for API Management
resource "azurerm_api_management_logger" "apim_logger" {
  name                = "${var.product_alias}-${var.env_alias}-apim-logger"
  api_management_name = azurerm_api_management.apim.name
  resource_group_name = data.azurerm_resource_group.rg.name
  resource_id         = azurerm_application_insights.function_insights.id

  application_insights {
    instrumentation_key = azurerm_application_insights.function_insights.instrumentation_key
  }
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
}