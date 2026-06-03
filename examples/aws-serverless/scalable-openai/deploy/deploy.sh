#!/bin/bash
set -e # exit if any command in this script fails
S3_BUCKET=lambda-s3-packages-329597159169-ap-southeast-2-an
upload_to_s3() {
	aws s3 cp $1 s3://${2}/
}

push_to_ecr() {
	AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
	AWS_REGION="ap-southeast-2"
	local image_name="$1"
	local dockerfile="$2"
	local ecr_uri="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${image_name}:latest"

	aws ecr get-login-password --region "$AWS_REGION" |
		docker login --username AWS --password-stdin \
			"${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

	docker buildx build \
		--platform linux/amd64 \
		--provenance=false \
		--tag "$ecr_uri" \
		--push \
		-f "$dockerfile" \
		.
}

echo "Creating request handler deployment package..."
create_request_handler_deployment_package() {
	pushd ../
	rm -rf dist_request_handler dist_request_handler.zip
	mkdir -p dist_request_handler
	uv export --no-hashes >requirements.txt
	if [[ ${1-} != "local" ]]; then
		uv pip install -r requirements.txt --target=dist_request_handler
	else
		uv pip install --force-reinstall --target=dist_request_handler --find-links ../../../ak-py/dist agentkernel[aws] || true
	fi
	cp -r lambda_request_handler.py config.yaml dist_request_handler/
	cd dist_request_handler && zip -r ../dist_request_handler.zip .
	popd || exit 1
}

# Create agent runner lambda deployment package
echo "Creating agent runner deployment package..."
create_agent_runner_deployment_package() {
	pushd ../
	rm -rf dist_agent_runner
	mkdir -p dist_agent_runner/data
	uv export --no-hashes >requirements.txt
	if [[ ${1-} != "local" ]]; then
		uv pip install -r requirements.txt --target=dist_agent_runner/data
	else
		uv pip install -r requirements.txt --target=dist_agent_runner/data --find-links ../../../ak-py/dist
		uv pip install --force-reinstall --target=dist_agent_runner/data --find-links ../../../ak-py/dist agentkernel[aws,openai] || true
	fi
	cp -r lambda_agent_runner.py config.yaml dist_agent_runner/data
	popd || exit 1
	cp Dockerfile.agent_runner ../dist_agent_runner/Dockerfile
}

echo "Creating response handler deployment package..."
create_response_handler_deployment_package() {
	pushd ../
	rm -rf dist_response_handler dist_response_handler.zip
	mkdir -p dist_response_handler
	uv export --no-hashes >requirements.txt
	if [[ ${1-} != "local" ]]; then
		uv pip install -r requirements.txt --target=dist_response_handler
	else
		uv pip install --force-reinstall --target=dist_response_handler --find-links ../../../ak-py/dist agentkernel[aws] || true
	fi
	cp -r lambda_response_handler.py config.yaml dist_response_handler/
	cd dist_response_handler && zip -r ../dist_response_handler.zip .
	popd || exit 1
}

create_request_handler_deployment_package $1
create_agent_runner_deployment_package $1
create_response_handler_deployment_package $1

pushd ../ || exit 1
# Upload deployment packages to S3
upload_to_s3 dist_request_handler.zip $S3_BUCKET
upload_to_s3 dist_response_handler.zip $S3_BUCKET

# Push to ECR
cd dist_agent_runner || exit 1
push_to_ecr "agent-runner-ext" Dockerfile
popd || exit 1


terraform init
terraform apply
