locals {
  service_name  = "${var.prefix}-runner"
  runner_member = "serviceAccount:${google_service_account.runner.email}"
  push_member   = "serviceAccount:${google_service_account.push.email}"
}
