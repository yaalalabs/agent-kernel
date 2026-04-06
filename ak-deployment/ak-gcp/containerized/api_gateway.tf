# Build the OpenAPI spec from our endpoints map.
# Each endpoint gets its own path in the API Gateway.
# GCP API Gateway (ESPv2) uses OpenAPI 2.0 (Swagger) — x-google-backend routes to Cloud Run.
locals {
  service_url = google_cloud_run_v2_service.service.uri

  # Flatten the endpoint map into a shape suitable for the path builders below
  openapi_paths_flat = {
    for key, ep in local.gateway_endpoints_map :
    ep.path => {
      method         = lower(ep.method) == "any" ? "x-google-allow" : lower(ep.method)
      is_any         = lower(ep.method) == "any"
      overwrite_path = ep.overwrite_path
      path           = ep.path
    }
  }

  # CORS header values — used for documentation; actual enforcement is in Cloud Run app
  cors_allow_methods_header = join(", ", var.cors_allow_methods)
  cors_allow_headers_header = join(", ", var.cors_allow_headers)
  cors_allow_origins_header = join(", ", var.cors_allow_origins)

  # Throttling
  enable_throttling    = var.throttling_rate_limit != null && var.throttling_burst_limit != null
  throttle_metric_name = "${local.prefix}-requests"

  # Per-operation quota cost added when throttling is enabled
  _quota_ext = local.enable_throttling ? {
    "x-google-quota" = {
      metricCosts = {
        (local.throttle_metric_name) = 1
      }
    }
  } : {}

  # CORS pre-flight OPTIONS operation — forwarded to Cloud Run for header injection
  # Helper closure-like locals used in each method builder below
  _options_op = {
    for path, ep in local.openapi_paths_flat :
    path => {
      summary     = "CORS pre-flight for ${ep.path}"
      operationId = "options-${replace(trim(ep.path, "/"), "/", "-")}"
      responses   = { "200" = { description = "CORS pre-flight" } }
      "x-google-backend" = {
        address          = "${local.service_url}${ep.overwrite_path}"
        path_translation = "CONSTANT_ADDRESS"
      }
    }
    if !ep.is_any
  }

  # Build path entries in separate typed for-loops to satisfy Terraform's type checker.
  # Merging different object shapes in a single ternary fails; splitting by method avoids it.

  _any_paths = {
    for path, ep in local.openapi_paths_flat :
    path => {
      "x-google-allow" = "all"
      "x-google-backend" = {
        address          = "${local.service_url}${ep.overwrite_path}"
        path_translation = "APPEND_PATH_TO_ADDRESS"
      }
      # Expose GET so the gateway registers the path; x-google-allow = "all"
      # makes every HTTP verb accepted (OPTIONS included — no separate CORS entry needed).
      get = {
        summary          = "Route to ${ep.path}"
        operationId      = "get-${replace(trim(ep.path, "/"), "/", "-")}"
        responses        = { "200" = { description = "Success" } }
        "x-google-backend" = {
          address          = "${local.service_url}${ep.overwrite_path}"
          path_translation = "APPEND_PATH_TO_ADDRESS"
        }
      }
    }
    if ep.is_any
  }

  _get_paths = {
    for path, ep in local.openapi_paths_flat :
    path => merge(
      {
        get = merge({ summary = "Route to ${ep.path}", operationId = "get-${replace(trim(ep.path, "/"), "/", "-")}", responses = { "200" = { description = "Success" } }, "x-google-backend" = { address = "${local.service_url}${ep.overwrite_path}", path_translation = "CONSTANT_ADDRESS" } }, local._quota_ext)
      },
      var.enable_cors ? { options = local._options_op[ep.path] } : {}
    )
    if !ep.is_any && ep.method == "get"
  }

  _post_paths = {
    for path, ep in local.openapi_paths_flat :
    path => merge(
      {
        post = merge({ summary = "Route to ${ep.path}", operationId = "post-${replace(trim(ep.path, "/"), "/", "-")}", responses = { "200" = { description = "Success" } }, "x-google-backend" = { address = "${local.service_url}${ep.overwrite_path}", path_translation = "CONSTANT_ADDRESS" } }, local._quota_ext)
      },
      var.enable_cors ? { options = local._options_op[ep.path] } : {}
    )
    if !ep.is_any && ep.method == "post"
  }

  _put_paths = {
    for path, ep in local.openapi_paths_flat :
    path => merge(
      {
        put = merge({ summary = "Route to ${ep.path}", operationId = "put-${replace(trim(ep.path, "/"), "/", "-")}", responses = { "200" = { description = "Success" } }, "x-google-backend" = { address = "${local.service_url}${ep.overwrite_path}", path_translation = "CONSTANT_ADDRESS" } }, local._quota_ext)
      },
      var.enable_cors ? { options = local._options_op[ep.path] } : {}
    )
    if !ep.is_any && ep.method == "put"
  }

  _delete_paths = {
    for path, ep in local.openapi_paths_flat :
    path => merge(
      {
        delete = merge({ summary = "Route to ${ep.path}", operationId = "delete-${replace(trim(ep.path, "/"), "/", "-")}", responses = { "200" = { description = "Success" } }, "x-google-backend" = { address = "${local.service_url}${ep.overwrite_path}", path_translation = "CONSTANT_ADDRESS" } }, local._quota_ext)
      },
      var.enable_cors ? { options = local._options_op[ep.path] } : {}
    )
    if !ep.is_any && ep.method == "delete"
  }

  _patch_paths = {
    for path, ep in local.openapi_paths_flat :
    path => merge(
      {
        patch = merge({ summary = "Route to ${ep.path}", operationId = "patch-${replace(trim(ep.path, "/"), "/", "-")}", responses = { "200" = { description = "Success" } }, "x-google-backend" = { address = "${local.service_url}${ep.overwrite_path}", path_translation = "CONSTANT_ADDRESS" } }, local._quota_ext)
      },
      var.enable_cors ? { options = local._options_op[ep.path] } : {}
    )
    if !ep.is_any && ep.method == "patch"
  }

  # Merge all per-method maps into the final paths block
  openapi_paths_block = merge(
    local._any_paths,
    local._get_paths,
    local._post_paths,
    local._put_paths,
    local._delete_paths,
    local._patch_paths,
  )

  # Base OpenAPI 2.0 spec
  openapi_base = {
    swagger = "2.0"
    info = {
      title       = "${var.product_display_name} API"
      description = "[${var.env_alias}] ${var.product_display_name} API"
      version     = var.api_version
    }
    schemes  = ["https"]
    produces = ["application/json"]
    paths    = local.openapi_paths_block
  }

  # Throttling quota extension.
  # GCP uses x-google-management for rate limiting (quota-based, consumer-level).
  # throttling_rate_limit (req/sec) is converted to per-minute for GCP quota units.
  openapi_throttling_ext = local.enable_throttling ? {
    "x-google-management" = {
      metrics = [{
        name        = local.throttle_metric_name
        displayName = "API Requests"
        valueType   = "INT64"
        metricKind  = "DELTA"
      }]
      quota = {
        limits = [
          {
            name   = "${local.prefix}-rate-limit"
            metric = local.throttle_metric_name
            unit   = "1/min/{project}"
            values = { STANDARD = var.throttling_rate_limit * 60 }
          },
          {
            name   = "${local.prefix}-burst-limit"
            metric = local.throttle_metric_name
            unit   = "1/min/{project}"
            values = { STANDARD = var.throttling_burst_limit }
          }
        ]
      }
    }
  } : {}

  # Final OpenAPI spec — base merged with optional throttling extension
  openapi_spec = merge(local.openapi_base, local.openapi_throttling_ext)
}

# API Gateway needs an API definition
resource "google_api_gateway_api" "api" {
  project  = var.project_id
  provider = google-beta
  api_id   = "${local.prefix}-api"
}

# The API config holds the OpenAPI spec.
# Config ID includes a hash of the full spec so a new config is created whenever
# endpoints, CORS, or throttling config changes (enabling zero-downtime updates).
resource "google_api_gateway_api_config" "config" {
  project       = var.project_id
  provider      = google-beta
  api           = google_api_gateway_api.api.api_id
  api_config_id = "${local.prefix}-config-${substr(md5(jsonencode(local.openapi_spec)), 0, 8)}"

  openapi_documents {
    document {
      path     = "openapi.json"
      contents = base64encode(jsonencode(local.openapi_spec))
    }
  }

  lifecycle {
    create_before_destroy = true
  }
}

# The gateway itself — this gets a public URL
resource "google_api_gateway_gateway" "gateway" {
  project    = var.project_id
  provider   = google-beta
  region     = var.region
  api_config = google_api_gateway_api_config.config.id
  gateway_id = "${local.prefix}-gateway"
}
