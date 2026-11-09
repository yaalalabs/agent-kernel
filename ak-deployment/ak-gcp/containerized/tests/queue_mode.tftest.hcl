# Plan-only checks of queue mode (#886), with stand-in providers: no GCP access needed.
# The module sources point at the registry, so run these on a copy whose ak-common sources point at
# ../common/modules, as the terraform-tests job in .github/workflows/test-reusable.yaml does.

mock_provider "google" {
  mock_data "google_project" {
    defaults = { number = "123456789" }
  }
}
mock_provider "google-beta" {}
mock_provider "docker" {}
mock_provider "random" {}
mock_provider "null" {}
mock_provider "time" {}

variables {
  project_id   = "test-project"
  region       = "us-central1"
  prefix       = "ak-test"
  package_path = "./dist"
}

run "queue_mode_is_the_default" {
  command = plan

  variables {
    agent_runner = { command = ["python", "-c", "from app import runner; runner()"] }
  }

  assert {
    condition     = length(module.pubsub) == 1 && length(module.agent_runner) == 1
    error_message = "with no queue_mode set, the deployment is queue mode"
  }
  assert {
    condition     = length(module.redis) == 1 && local.queue_env["AK_EXECUTION__RESPONSE_STORE__REDIS__URL"] != null
    error_message = "queue mode creates Memorystore by itself, without create_redis_cluster"
  }
}

run "single_service_is_unchanged" {
  command = plan

  variables {
    queue_mode = false
  }

  assert {
    condition     = length(module.redis) == 0
    error_message = "the single service creates no Memorystore unless asked"
  }

  assert {
    condition     = length(module.pubsub) == 0 && length(module.agent_runner) == 0
    error_message = "queue_mode = false must create no Pub/Sub objects and no worker pool"
  }
  assert {
    condition     = google_cloud_run_v2_service.service.template[0].containers[0].resources[0].cpu_idle == null
    error_message = "cpu_idle must stay unset outside queue mode"
  }
  assert {
    condition     = contains(keys(local.gateway_endpoints_map), "POST /api/v1/agent-multipart") || length([for k in keys(local.gateway_endpoints_map) : k if endswith(k, "-multipart")]) == 1
    error_message = "the multipart route stays outside queue mode"
  }
  assert {
    condition     = length([for e in google_cloud_run_v2_service.service.template[0].containers[0].env : e if startswith(e.name, "AK_EXECUTION__")]) == 0
    error_message = "no queue env outside queue mode"
  }
}

run "queue_mode_wires_both_tiers" {
  command = plan

  variables {
    queue_mode   = true
    agent_runner = { command = ["python", "-c", "from app import runner; runner()"] }
  }

  assert {
    condition     = length(module.pubsub) == 1 && length(module.agent_runner) == 1
    error_message = "queue mode creates the Pub/Sub objects and the worker pool"
  }
  assert {
    condition     = google_cloud_run_v2_service.service.template[0].containers[0].resources[0].cpu_idle == false
    error_message = "the edge keeps its CPU allocated in queue mode"
  }
  assert {
    condition = alltrue([for name in [
      "AK_EXECUTION__QUEUES__PUBSUB__PROJECT_ID", "AK_EXECUTION__QUEUES__PUBSUB__INPUT_TOPIC",
      "AK_EXECUTION__QUEUES__PUBSUB__OUTPUT_SUBSCRIPTION", "AK_EXECUTION__RESPONSE_STORE__REDIS__URL",
      "AK_EXECUTION__QUEUES__INPUT__MAX_RECEIVE_COUNT", "AK_EXECUTION__MODE",
    ] : contains([for e in google_cloud_run_v2_service.service.template[0].containers[0].env : e.name], name)])
    error_message = "the edge gets the queue coordinates"
  }
  assert {
    condition     = !contains([for e in google_cloud_run_v2_service.service.template[0].containers[0].env : e.name], "AK_EXECUTION__QUEUES__TYPE")
    error_message = "Terraform never declares the transport type"
  }
  assert {
    condition     = local.queue_env["AK_EXECUTION__QUEUES__INPUT__MAX_RECEIVE_COUNT"] == "4" && local.queue_env["AK_EXECUTION__QUEUES__PUBSUB__INPUT_TOPIC"] == "ak-test-agent-input"
    error_message = "max_receive_count is deliveries minus one (default 5 here), and topics are prefixed"
  }
  assert {
    condition     = length([for k in keys(local.gateway_endpoints_map) : k if endswith(k, "-multipart")]) == 0 && length([for k in keys(local.gateway_endpoints_map) : k if startswith(k, "GET ")]) == 0
    error_message = "queue mode drops multipart, and rest_sync adds no poll route"
  }
  assert {
    condition     = length(google_pubsub_topic_iam_member.edge_publish) == 4 && length(google_pubsub_subscription_iam_member.edge_output) == 2
    error_message = "the edge gets publish+viewer on the input and output dead-letter topics, subscriber+viewer on the output subscription"
  }
}

run "rest_async_adds_the_poll_route" {
  command = plan

  variables {
    queue_mode     = true
    execution_mode = "rest_async"
    agent_runner   = { command = ["python", "-c", "from app import runner; runner()"] }
  }

  assert {
    condition     = length([for k in keys(local.gateway_endpoints_map) : k if startswith(k, "GET ")]) == 1
    error_message = "rest_async polls with GET on the chat path"
  }
}

run "the_runner_never_reads_the_request_subscription" {
  command = plan

  variables {
    agent_runner = { command = ["python", "-c", "from app import runner; runner()"] }
  }

  assert {
    condition     = !contains(keys(local.queue_env), "AK_EXECUTION__QUEUES__PUBSUB__INPUT_SUBSCRIPTION")
    error_message = "the request subscription depends on the runner's URL, so the runner's environment must not reference it"
  }
  assert {
    condition     = contains(keys(local.queue_env), "AK_EXECUTION__QUEUES__PUBSUB__OUTPUT_SUBSCRIPTION")
    error_message = "the edge pulls replies from the output subscription"
  }
}

run "socket_modes_are_rejected" {
  command = plan
  variables {
    queue_mode     = true
    execution_mode = "async"
    agent_runner   = { command = ["x"] }
  }
  expect_failures = [var.execution_mode]
}

run "runner_needs_its_own_entry_point" {
  command         = plan
  expect_failures = [var.agent_runner]
}

run "runner_scaling_bounds_are_checked" {
  command = plan
  variables {
    agent_runner = { command = ["x"], min_instance_count = 5, max_instance_count = 2 }
  }
  expect_failures = [var.agent_runner]
}
