# Plan-only checks with stand-in providers: no GCP access needed. Run with `terraform test`.

mock_provider "google" {
  mock_data "google_project" {
    defaults = { number = "123456789" }
  }
}

variables {
  project_id       = "test-project"
  region           = "us-central1"
  prefix           = "ak-test"
  image_url        = "us-docker.pkg.dev/test/ak-test/ak-test:1"
  command          = ["python", "-c", "from app import runner; runner()"]
  vpc_connector_id = "projects/test-project/locations/us-central1/connectors/c"
  pubsub = {
    topics             = { input = "ak-test-agent-input", output = "ak-test-agent-output" }
    dead_letter_topics = { input = "ak-test-agent-input-dlq", output = "ak-test-agent-output-dlq" }
  }
}

run "a_private_push_driven_service_with_no_ten_minute_cap" {
  command = plan

  assert {
    condition     = google_cloud_run_v2_service.runner.template[0].timeout == "3600s"
    error_message = "agent runs are not capped at 10 minutes: the request timeout is Cloud Run's maximum"
  }
  assert {
    condition     = google_cloud_run_v2_service.runner.ingress == "INGRESS_TRAFFIC_INTERNAL_ONLY"
    error_message = "only same-project traffic (Pub/Sub push) reaches the runner"
  }
  assert {
    condition     = google_cloud_run_v2_service.runner.template[0].scaling[0].min_instance_count == 0 && google_cloud_run_v2_service.runner.template[0].max_instance_request_concurrency == 5
    error_message = "it scales to zero and runs up to 5 agent runs per instance by default"
  }
  assert {
    condition     = google_cloud_run_v2_service_iam_member.push_invoker.role == "roles/run.invoker"
    error_message = "the push identity may invoke the runner"
  }
  assert {
    condition     = length(google_pubsub_topic_iam_member.runner_publish) == 4
    error_message = "publish + viewer on the output topic and the input dead-letter topic"
  }
}
