region = "us-east-2"
prefix = "ak-openai-sse-dev-examples"
# The shared examples VPC in us-east-2 (created by the weekly CI base deployment) and its private subnets
vpc_id             = "vpc-0beb069c4f53d462e"
private_subnet_ids = ["subnet-0eb8400eed69f0090", "subnet-0681fc8232448f33f"]

# Set by deploy.sh. Without it, point these at your own artifacts:
# request_handler_lambda_package_s3  = { bucket = "<bucket>", key = "dist_request_handler.zip" }
# response_handler_lambda_package_s3 = { bucket = "<bucket>", key = "dist_response_handler.zip" }
# agent_runner_ecr_image_uri         = "<account>.dkr.ecr.<region>.amazonaws.com/agent-runner-ext:latest"
