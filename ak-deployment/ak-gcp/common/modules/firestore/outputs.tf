output "database_name" {
  description = "Firestore database name"
  value       = google_firestore_database.db.name
}

output "database_id" {
  description = "Firestore database ID"
  value       = google_firestore_database.db.name
}

output "collection_name" {
  description = "Firestore collection name"
  value       = var.collection_name
}

output "project_id" {
  description = "GCP project ID where the database lives"
  value       = var.project_id
}
