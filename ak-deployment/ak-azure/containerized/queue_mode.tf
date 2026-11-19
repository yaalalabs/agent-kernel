# Queue mode: the Container App above becomes the edge (IOHandler) and an agent runner app consumes the
# Service Bus input queue. Every resource here exists only when var.queue_mode is true.

locals {
  # Agent Kernel's default (execution.queues.input/output.max_receive_count). The broker ceiling sits one
  # above it so Agent Kernel's permanent-failure hook fires before Service Bus dead-letters the message.
  max_receive_count = 3

  servicebus_namespace = var.queue_mode ? azurerm_servicebus_namespace.queues[0].name : null

  # Coordinates only: execution.queues.type and execution.response_store.type come from the app's config.yaml.
  queue_env = var.queue_mode ? {
    "AK_EXECUTION__QUEUES__INPUT__URL"                = "https://${local.servicebus_namespace}.servicebus.windows.net/${azurerm_servicebus_queue.input[0].name}"
    "AK_EXECUTION__QUEUES__OUTPUT__URL"               = "https://${local.servicebus_namespace}.servicebus.windows.net/${azurerm_servicebus_queue.output[0].name}"
    "AK_EXECUTION__QUEUES__INPUT__MAX_RECEIVE_COUNT"  = tostring(local.max_receive_count)
    "AK_EXECUTION__QUEUES__OUTPUT__MAX_RECEIVE_COUNT" = tostring(local.max_receive_count)
    "AK_EXECUTION__RESPONSE_STORE__REDIS__URL"        = "" # filled from the redis-url secret
  } : {}
}

resource "azurerm_servicebus_namespace" "queues" {
  count               = var.queue_mode ? 1 : 0
  name                = "${var.prefix}-queues" # Service Bus rejects names ending in -sb
  location            = var.region
  resource_group_name = data.azurerm_resource_group.rg.name
  sku                 = "Standard"
  local_auth_enabled  = false # managed identity only, including the KEDA scale rule
  minimum_tls_version = "1.2"
  tags                = var.tags
}

resource "azurerm_servicebus_queue" "input" {
  count                                   = var.queue_mode ? 1 : 0
  name                                    = "input"
  namespace_id                            = azurerm_servicebus_namespace.queues[0].id
  requires_session                        = true
  requires_duplicate_detection            = true
  duplicate_detection_history_time_window = "PT5M"
  lock_duration                           = "PT1M"
  max_delivery_count                      = local.max_receive_count + 1
  dead_lettering_on_message_expiration    = true
}

resource "azurerm_servicebus_queue" "output" {
  count                                   = var.queue_mode ? 1 : 0
  name                                    = "output"
  namespace_id                            = azurerm_servicebus_namespace.queues[0].id
  requires_session                        = true
  requires_duplicate_detection            = true
  duplicate_detection_history_time_window = "PT5M"
  lock_duration                           = "PT1M"
  max_delivery_count                      = local.max_receive_count + 1
  dead_lettering_on_message_expiration    = true
}

resource "azurerm_container_app" "agent_runner" {
  count                        = var.queue_mode ? 1 : 0
  name                         = "${var.prefix}-runner"
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = data.azurerm_resource_group.rg.name
  revision_mode                = "Single"

  registry {
    server               = module.docker_image.login_server
    username             = module.docker_image.admin_username
    password_secret_name = "acr-password"
  }

  dynamic "secret" {
    for_each = local.app_secrets
    content {
      name  = secret.key
      value = secret.value
    }
  }

  template {
    min_replicas                     = var.container_min_replicas
    max_replicas                     = var.container_max_replicas
    termination_grace_period_seconds = 300 # lets an in-flight agent turn finish before the pod stops

    container {
      name    = "${var.prefix}-runner"
      image   = "${module.docker_image.docker_image_uri}:latest"
      command = var.agent_runner_command
      cpu     = var.is_production ? "1.0" : "0.5"
      memory  = var.is_production ? "2Gi" : "1Gi"

      dynamic "env" {
        for_each = local.app_env
        content {
          name        = env.key
          value       = env.value != "" ? env.value : null
          secret_name = env.value == "" ? lookup(local.env_secret_refs, env.key, null) : null
        }
      }
    }

    custom_scale_rule {
      name             = "servicebus-input"
      custom_rule_type = "azure-servicebus"
      metadata = {
        namespace    = local.servicebus_namespace
        queueName    = azurerm_servicebus_queue.input[0].name
        messageCount = "5" # Agent Kernel's no_of_consumers default: one replica per 5 waiting messages
      }
      identity_id = "System"
    }
  }

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags

  depends_on = [module.docker_image]
}

# Edge: send requests, receive replies.
resource "azurerm_role_assignment" "edge_input_sender" {
  count                = var.queue_mode ? 1 : 0
  scope                = azurerm_servicebus_queue.input[0].id
  role_definition_name = "Azure Service Bus Data Sender"
  principal_id         = azurerm_container_app.app.identity[0].principal_id
}

resource "azurerm_role_assignment" "edge_output_receiver" {
  count                = var.queue_mode ? 1 : 0
  scope                = azurerm_servicebus_queue.output[0].id
  role_definition_name = "Azure Service Bus Data Receiver"
  principal_id         = azurerm_container_app.app.identity[0].principal_id
}

# Runner: receive requests, send replies. Data Owner (not Receiver) on input because the KEDA scaler reads the
# queue's runtime properties, which Service Bus treats as a manage operation.
resource "azurerm_role_assignment" "runner_input_owner" {
  count                = var.queue_mode ? 1 : 0
  scope                = azurerm_servicebus_queue.input[0].id
  role_definition_name = "Azure Service Bus Data Owner"
  principal_id         = azurerm_container_app.agent_runner[0].identity[0].principal_id
}

resource "azurerm_role_assignment" "runner_output_sender" {
  count                = var.queue_mode ? 1 : 0
  scope                = azurerm_servicebus_queue.output[0].id
  role_definition_name = "Azure Service Bus Data Sender"
  principal_id         = azurerm_container_app.agent_runner[0].identity[0].principal_id
}
