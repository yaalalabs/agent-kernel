data "azurerm_resource_group" "current_group" {
  name = var.resource_group_name
}

data "azurerm_client_config" "current" {}

locals {
  subscription_suffix = substr(
    sha1(data.azurerm_client_config.current.subscription_id),
    0,
    6
  )
}

locals {
  source_path = "${path.root}/${var.source_path}"
  path_include = ["**"]
  path_exclude = ["**/__pycache__/**"]
  files_include = setunion([for f in local.path_include : fileset(local.source_path, f)]...)
  files_exclude = setunion([for f in local.path_exclude : fileset(local.source_path, f)]...)
  files = sort(setsubtract(local.files_include, local.files_exclude))

  dir_sha = sha1(join("", [for f in local.files : filesha1("${local.source_path}/${f}")]))
  image_name = "${var.product_alias}-${var.env_alias}-${var.module_name}"
}

resource "azurerm_container_registry" "acr" {
  name = lower(replace(
    "${var.product_alias}${var.env_alias}${var.module_name}${local.subscription_suffix}",
    "/[^a-z0-9]/",
    ""
  ))

  resource_group_name = data.azurerm_resource_group.current_group.name
  location            = data.azurerm_resource_group.current_group.location
  sku                 = "Basic"
  admin_enabled       = true
}


provider "docker" {
  registry_auth {
    address  = azurerm_container_registry.acr.login_server
    username = azurerm_container_registry.acr.admin_username
    password = azurerm_container_registry.acr.admin_password
  }

}

resource "docker_image" "image" {
  name = "${azurerm_container_registry.acr.login_server}/${local.image_name}"
  keep_locally = false

  build {
    no_cache = true
    context = local.source_path
  }
  triggers = {
    dir_sha = local.dir_sha
  }
}

resource "docker_registry_image" "image" {
  name = docker_image.image.name
  keep_remotely = true
}
