#!/bin/bash
set -e

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

# Create a zip file of the app code
create_deployment_package() {
    pushd ../
    rm -rf dist
    mkdir -p dist/data
    uv export --no-hashes > requirements.txt
    if [[ ${1-} != "local" ]]; then
      uv pip install -r requirements.txt --target=dist/data
    else
      uv pip install -r requirements.txt --target=dist/data  --find-links ../../../ak-py/dist
      uv pip install --force-reinstall --target=dist/data --find-links ../../../ak-py/dist agentkernel[adk,api,aws,test] || true
    fi
    cp -r app.py config.yaml dist/data
    popd || exit 1
    cp Dockerfile ../dist/
}

create_deployment_package $1

pushd ../ || exit 1
push_to_ecr "openai-dynamodb-ext" "Dockerfile"
popd || exit 1

terraform init
terraform apply