terraform {
  required_version = ">= 1.9.5"
  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "3.6.2"
    }
  }
}

data "azurerm_resource_group" "current_group" {
  count = var.enabled ? 1 : 0
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
  count = var.enabled ? 1 : 0
  name = lower(replace(
    "${var.product_alias}${var.env_alias}${var.module_name}${local.subscription_suffix}",
    "/[^a-z0-9]/",
    ""
  ))

  resource_group_name = data.azurerm_resource_group.current_group[0].name
  location            = data.azurerm_resource_group.current_group[0].location
  sku                 = "Basic"
  admin_enabled       = true
}


provider "docker" {
  registry_auth {
    address  = var.enabled ? azurerm_container_registry.acr[0].login_server : "localhost"
    username = var.enabled ? azurerm_container_registry.acr[0].admin_username : null
    password = var.enabled ? azurerm_container_registry.acr[0].admin_password : null
  }
}


resource "docker_image" "image" {
  count = var.enabled ? 1 : 0
  name = "${azurerm_container_registry.acr[0].login_server}/${local.image_name}"
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
  count = var.enabled ? 1 : 0
  name = docker_image.image[0].name
  keep_remotely = true
}
