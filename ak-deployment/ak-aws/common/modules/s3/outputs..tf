output "source_storage_s3_bucket" {
  value = aws_s3_bucket.source-storage.id
  description = "Source storage bucket ID"
}