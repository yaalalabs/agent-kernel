# Identities and permissions: the runner's own service account and its rights, and the push
# identity Pub/Sub signs each request with, which alone may invoke the runner.

data "google_project" "project" {
  project_id = var.project_id
}

resource "google_service_account" "runner" {
  project      = var.project_id
  account_id   = "${substr(var.prefix, 0, min(length(var.prefix), 26))}-rnr"
  display_name = "Agent runner SA for ${var.prefix}"
}

resource "google_project_iam_member" "runner_logging" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = local.runner_member
}

resource "google_project_iam_member" "runner_firestore" {
  count   = var.grant_firestore ? 1 : 0
  project = var.project_id
  role    = "roles/datastore.user"
  member  = local.runner_member
}

# Publish replies, and copy permanently failed requests to the input dead-letter topic. viewer lets
# the transport verify the output topic before its first publish.
resource "google_pubsub_topic_iam_member" "runner_publish" {
  for_each = {
    for pair in setproduct(["output", "input_dead_letter"], ["roles/pubsub.publisher", "roles/pubsub.viewer"]) :
    "${pair[0]}:${pair[1]}" => { topic = pair[0] == "output" ? var.pubsub.topics["output"] : var.pubsub.dead_letter_topics["input"], role = pair[1] }
  }

  project = var.project_id
  topic   = each.value.topic
  role    = each.value.role
  member  = local.runner_member
}

# The identity Pub/Sub signs each push with. Only it may call the runner.
resource "google_service_account" "push" {
  project      = var.project_id
  account_id   = "${substr(var.prefix, 0, min(length(var.prefix), 26))}-psh"
  display_name = "Pub/Sub push identity for ${var.prefix}"
}

resource "google_cloud_run_v2_service_iam_member" "push_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.runner.name
  role     = "roles/run.invoker"
  member   = local.push_member
}

# Pub/Sub's service agent mints the push identity's tokens (required on projects created before
# April 2021, harmless on newer ones).
resource "google_service_account_iam_member" "push_token_creator" {
  service_account_id = google_service_account.push.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}
