# Build the OpenAPI spec from our endpoints map.
# Each endpoint gets its own path in the API Gateway.
# GCP API Gateway (ESPv2) uses OpenAPI 2.0 (Swagger) — x-google-backend routes to Cloud Run.
locals {
  service_url = google_cloud_run_v2_service.service.uri

  # Flatten the endpoint map into a shape suitable for the path builders below. Entries stay keyed
  # by method and path, as gateway_endpoints_map is: several methods may share a path (GET and POST
  # on the chat path in rest_async queue mode), so openapi_paths_block groups them per path.
  openapi_paths_flat = {
    for key, ep in local.gateway_endpoints_map :
    key => {
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
  throttle_metric_name = "${substr(var.prefix, 0, min(length(var.prefix), 45))}-${local.deployment_id}-req"

  # Per-operation quota cost added when throttling is enabled
  _quota_ext = local.enable_throttling ? {
    "x-google-quota" = {
      metricCosts = {
        (local.throttle_metric_name) = 1
      }
    }
  } : {}

  # CORS pre-flight OPTIONS operation — forwarded to Cloud Run for header injection
  # One per path, routed through the path's first non-ANY endpoint (map iteration is in key order,
  # so the choice is stable).
  _non_any_endpoints_by_path = {
    for key, ep in local.openapi_paths_flat :
    ep.path => ep...
    if !ep.is_any
  }
  _options_op = {
    for path, eps in local._non_any_endpoints_by_path :
    path => {
      summary     = "CORS pre-flight for ${eps[0].path}"
      operationId = "options-${replace(trim(eps[0].path, "/"), "/", "-")}"
      responses   = { "200" = { description = "CORS pre-flight" } }
      "x-google-backend" = {
        address          = "${local.service_url}${eps[0].overwrite_path}"
        path_translation = "CONSTANT_ADDRESS"
        deadline         = var.backend_deadline
      }
    }
  }

  # Build path entries in separate typed for-loops to satisfy Terraform's type checker.
  # Merging different object shapes in a single ternary fails; splitting by method avoids it.

  _any_paths = {
    for key, ep in local.openapi_paths_flat :
    ep.path => {
      "x-google-allow" = "all"
      "x-google-backend" = {
        address          = local.service_url
        path_translation = "APPEND_PATH_TO_ADDRESS"
        deadline         = var.backend_deadline
      }
      # Expose GET so the gateway registers the path; x-google-allow = "all"
      # makes every HTTP verb accepted (OPTIONS included — no separate CORS entry needed).
      get = {
        summary     = "Route to ${ep.path}"
        operationId = "get-${replace(trim(ep.path, "/"), "/", "-")}"
        responses   = { "200" = { description = "Success" } }
        "x-google-backend" = {
          address          = local.service_url
          path_translation = "APPEND_PATH_TO_ADDRESS"
          deadline         = var.backend_deadline
        }
      }
    }
    if ep.is_any
  }

  _get_paths = {
    for key, ep in local.openapi_paths_flat :
    ep.path => {
      get = merge({ summary = "Route to ${ep.path}", operationId = "get-${replace(trim(ep.path, "/"), "/", "-")}", responses = { "200" = { description = "Success" } }, "x-google-backend" = { address = "${local.service_url}${ep.overwrite_path}", path_translation = "CONSTANT_ADDRESS", deadline = var.backend_deadline } }, local._quota_ext)
    }
    if !ep.is_any && ep.method == "get"
  }

  _post_paths = {
    for key, ep in local.openapi_paths_flat :
    ep.path => {
      post = merge({ summary = "Route to ${ep.path}", operationId = "post-${replace(trim(ep.path, "/"), "/", "-")}", responses = { "200" = { description = "Success" } }, "x-google-backend" = { address = "${local.service_url}${ep.overwrite_path}", path_translation = "CONSTANT_ADDRESS", deadline = var.backend_deadline } }, local._quota_ext)
    }
    if !ep.is_any && ep.method == "post"
  }

  _put_paths = {
    for key, ep in local.openapi_paths_flat :
    ep.path => {
      put = merge({ summary = "Route to ${ep.path}", operationId = "put-${replace(trim(ep.path, "/"), "/", "-")}", responses = { "200" = { description = "Success" } }, "x-google-backend" = { address = "${local.service_url}${ep.overwrite_path}", path_translation = "CONSTANT_ADDRESS", deadline = var.backend_deadline } }, local._quota_ext)
    }
    if !ep.is_any && ep.method == "put"
  }

  _delete_paths = {
    for key, ep in local.openapi_paths_flat :
    ep.path => {
      delete = merge({ summary = "Route to ${ep.path}", operationId = "delete-${replace(trim(ep.path, "/"), "/", "-")}", responses = { "200" = { description = "Success" } }, "x-google-backend" = { address = "${local.service_url}${ep.overwrite_path}", path_translation = "CONSTANT_ADDRESS", deadline = var.backend_deadline } }, local._quota_ext)
    }
    if !ep.is_any && ep.method == "delete"
  }

  _patch_paths = {
    for key, ep in local.openapi_paths_flat :
    ep.path => {
      patch = merge({ summary = "Route to ${ep.path}", operationId = "patch-${replace(trim(ep.path, "/"), "/", "-")}", responses = { "200" = { description = "Success" } }, "x-google-backend" = { address = "${local.service_url}${ep.overwrite_path}", path_translation = "CONSTANT_ADDRESS", deadline = var.backend_deadline } }, local._quota_ext)
    }
    if !ep.is_any && ep.method == "patch"
  }

  # One path object per path: every method served on it, plus its CORS pre-flight. try() rather
  # than lookup(): the per-method objects have different shapes, which lookup's default cannot take.
  openapi_paths_block = {
    for path in distinct([for ep in values(local.openapi_paths_flat) : ep.path]) :
    path => merge(
      try(local._any_paths[path], {}),
      try(local._get_paths[path], {}),
      try(local._post_paths[path], {}),
      try(local._put_paths[path], {}),
      try(local._delete_paths[path], {}),
      try(local._patch_paths[path], {}),
      var.enable_cors && contains(keys(local._options_op), path) ? { options = local._options_op[path] } : {},
    )
  }

  # Base OpenAPI 2.0 spec (no security — added conditionally below)
  openapi_base = {
    swagger = "2.0"
    info = {
      title       = "${var.product_display_name} API"
      description = "[${var.prefix}] ${var.product_display_name} API"
      version     = var.api_version
    }
    schemes  = ["https"]
    produces = ["application/json"]
    paths    = local.openapi_paths_block
  }

  # Throttling quota extension.
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
            name   = "${substr(var.prefix, 0, min(length(var.prefix), 40))}-${local.deployment_id}-rate"
            metric = local.throttle_metric_name
            unit   = "1/min/{project}"
            values = { STANDARD = var.throttling_rate_limit * 60 }
          },
          {
            name   = "${substr(var.prefix, 0, min(length(var.prefix), 39))}-${local.deployment_id}-burst"
            metric = local.throttle_metric_name
            unit   = "1/min/{project}"
            values = { STANDARD = var.throttling_burst_limit }
          }
        ]
      }
    }
  } : {}

  # Build the final OpenAPI spec as a JSON string.
  # Security fields (securityDefinitions, security) are conditionally included using
  # a string-level ternary — Terraform's type system prevents conditional object keys
  # inside map literals, so we produce two JSON strings and pick one.
  # GCP API Gateway rejects null values so omitting is the only valid approach.
  openapi_spec_json = local.create_authorizer ? jsonencode(merge(
    local.openapi_base,
    local.openapi_throttling_ext,
    {
      securityDefinitions = {
        jwt_auth = {
          authorizationUrl     = ""
          flow                 = "implicit"
          type                 = "oauth2"
          "x-google-issuer"    = var.authorizer.issuer
          "x-google-jwks_uri"  = var.authorizer.jwks_uri
          "x-google-audiences" = join(",", var.authorizer.audiences)
        }
      }
      security = [{ jwt_auth = [] }]
    }
  )) : jsonencode(merge(local.openapi_base, local.openapi_throttling_ext))
}

# API Gateway needs an API definition
resource "google_api_gateway_api" "api" {
  project  = var.project_id
  provider = google-beta
  api_id   = local.api_id
}

# The API config holds the OpenAPI spec.
# Config ID includes a hash of the full spec so a new config is created whenever
# endpoints, CORS, or throttling config changes (enabling zero-downtime updates).
resource "google_api_gateway_api_config" "config" {
  project       = var.project_id
  provider      = google-beta
  api           = google_api_gateway_api.api.api_id
  api_config_id = "${var.prefix}-config-${substr(md5(local.openapi_spec_json), 0, 8)}"

  openapi_documents {
    document {
      path     = "openapi.json"
      contents = base64encode(local.openapi_spec_json)
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
  gateway_id = local.gateway_id
}
