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
      uv pip install -r requirements.txt --target=dist/data --find-links ../../../ak-py/dist --upgrade-package agentkernel --reinstall-package agentkernel || true
    fi
    cp -r app.py config.yaml dist/data
    popd || exit 1
    cp Dockerfile ../dist/
}


function read_tfvar() {
	awk -F'=' -v k="$1" '$1 ~ "^[[:space:]]*"k"[[:space:]]*$" {gsub(/[" ]/, "", $2); print $2; exit}' terraform.tfvars
}

function wait_for_ecs_stable() {
	local region product_alias env_alias module_name cluster services
	region=$(read_tfvar region)
	product_alias=$(read_tfvar product_alias)
	env_alias=$(read_tfvar env_alias)
	module_name=$(read_tfvar module_name)
	cluster="${product_alias}-${env_alias}-${module_name}"

	echo "Resolving ECS services in cluster '${cluster}' (region ${region})..."
	services=$(aws ecs list-services --cluster "$cluster" --region "$region" \
		--query 'serviceArns' --output text)
	if [[ -z "$services" || "$services" == "None" ]]; then
		echo "Could not find any ECS service in cluster '${cluster}'"
		return 1
	fi

	echo "Waiting for ECS services to become stable: ${services}"
	if ! aws ecs wait services-stable --cluster "$cluster" --services $services --region "$region"; then
		echo "ECS services did not reach a stable state"
		return 1
	fi
	echo "ECS services are stable and serving traffic."
}

create_deployment_package $1

pushd ../dist || exit 1
push_to_ecr "openai-dynamodb-ext" "Dockerfile"
popd || exit 1

terraform init
terraform apply

wait_for_ecs_stable