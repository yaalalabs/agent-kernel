region        = "ap-southeast-2"
product_alias = "ak-openai-srvls-qmde"
env_alias     = "dev"
module_name   = "examples"
request_handler_lambda_package_s3 = {
  bucket = "lambda-s3-packages-329597159169-ap-southeast-2-an"
  key    = "dist_request_handler.zip"
  # version_id = "<object-version-id>"
}

response_handler_lambda_package_s3 = {
  bucket = "lambda-s3-packages-329597159169-ap-southeast-2-an"
  key    = "dist_response_handler.zip"
  # version_id = "<object-version-id>"
}

agent_runner_ecr_image_uri = "329597159169.dkr.ecr.ap-southeast-2.amazonaws.com/agent-runner-ext:latest"
