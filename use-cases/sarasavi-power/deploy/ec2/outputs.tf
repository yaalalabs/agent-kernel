output "public_ip" {
  value = aws_eip.app.public_ip
}

output "hostname" {
  description = "sslip.io hostname Caddy will get a Let's Encrypt cert for"
  value       = "${replace(aws_eip.app.public_ip, ".", "-")}.sslip.io"
}

output "webhook_url" {
  description = "Paste this as the callback URL in the Meta app dashboard"
  value       = "https://${replace(aws_eip.app.public_ip, ".", "-")}.sslip.io/whatsapp/webhook"
}

output "dynamodb_table" {
  value = aws_dynamodb_table.sessions.name
}

output "ssh" {
  value = "ssh ubuntu@${aws_eip.app.public_ip}"
}
