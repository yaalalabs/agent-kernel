output "rest_api_arn" {
  value = aws_api_gateway_rest_api.rest_api.arn
}

output "rest_api_gateway_id" {
  value = aws_api_gateway_rest_api.rest_api.id
}