# Database name — Firestore allows multiple named databases per project
locals {
  database_id = "${var.product_alias}-${var.env_alias}-${var.module_name}"
}

# Create a Firestore database in Native mode
# This is the GCP equivalent of DynamoDB or CosmosDB
resource "google_firestore_database" "db" {
  project     = var.project_id
  name        = local.database_id
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  deletion_policy             = var.deletion_protection ? "ABANDON" : "DELETE"
  point_in_time_recovery_enablement = var.point_in_time_recovery ? "POINT_IN_TIME_RECOVERY_ENABLED" : "POINT_IN_TIME_RECOVERY_DISABLED"
}

# TTL policy — automatically deletes old session records
# Works like DynamoDB TTL or CosmosDB TTL
resource "google_firestore_field" "ttl" {
  project    = var.project_id
  database   = google_firestore_database.db.name
  collection = var.collection_name
  field      = var.ttl_field

  ttl_config {}
}
