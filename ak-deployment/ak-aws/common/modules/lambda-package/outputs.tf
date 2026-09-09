output "s3_bucket" {
  description = "S3 bucket containing the package"
  value       = aws_s3_object.source_code.bucket
}

output "s3_key" {
  description = "S3 object key for the package"
  value       = aws_s3_object.source_code.key
}

output "s3_object_version" {
  description = "Version ID of the S3 object"
  value       = aws_s3_object.source_code.version_id
}

output "package_etag" {
  description = "ETag of the package"
  value       = aws_s3_object.source_code.etag
}
