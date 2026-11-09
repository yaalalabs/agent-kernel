# Plan-only checks with stand-in providers: no GCP access needed. Run with `terraform test`.

mock_provider "google" {
  mock_data "google_project" {
    defaults = { number = "123456789" }
  }
}

variables {
  project_id                       = "test-project"
  prefix                           = "ak-test"
  input_push_endpoint              = "https://ak-test-runner.run.app/pubsub/push"
  input_push_service_account_email = "ak-test-psh@test-project.iam.gserviceaccount.com"
}

run "requests_are_pushed_and_replies_pulled" {
  command = plan

  assert {
    condition     = google_pubsub_subscription.input.push_config[0].push_endpoint == "https://ak-test-runner.run.app/pubsub/push"
    error_message = "the request subscription pushes to the runner"
  }
  assert {
    condition     = google_pubsub_subscription.input.push_config[0].oidc_token[0].service_account_email == "ak-test-psh@test-project.iam.gserviceaccount.com"
    error_message = "pushes are signed with the push identity"
  }
  assert {
    condition     = google_pubsub_subscription.input.ack_deadline_seconds == 600 && google_pubsub_subscription.input.enable_message_ordering
    error_message = "push waits Pub/Sub's maximum, 600 s, and keeps session order"
  }
  assert {
    condition     = length(google_pubsub_subscription.output.push_config) == 0 && google_pubsub_subscription.output.ack_deadline_seconds == 10
    error_message = "replies stay a pull subscription with the transport's 10 s deadline"
  }
  assert {
    condition     = google_pubsub_subscription.input.dead_letter_policy[0].max_delivery_attempts == 5
    error_message = "the dead-letter backstop is clamped to Pub/Sub's minimum of 5"
  }
}
