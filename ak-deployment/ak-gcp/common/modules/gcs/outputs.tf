output "bucket_name" {
  description = "Name of the GCS bucket"
  value       = google_storage_bucket.source_storage.name
}

output "bucket_url" {
  description = "URL of the GCS bucket"
  value       = google_storage_bucket.source_storage.url
}

output "bucket_self_link" {
  description = "Self link of the GCS bucket"
  value       = google_storage_bucket.source_storage.self_link
}
