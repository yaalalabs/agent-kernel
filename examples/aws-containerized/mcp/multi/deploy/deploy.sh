#!/bin/bash

# Create a zip file of the app code
create_deployment_package() {
    pushd ../
    rm -rf dist
    mkdir -p dist/data
    uv export --no-hashes > requirements.txt
    if [[ ${1-} != "local" ]]; then
      uv pip install -r requirements.txt --target=dist/data
    else
      uv pip install -r requirements.txt --target=dist/data --find-links ../../../../ak-py/dist --upgrade-package agentkernel --reinstall-package agentkernel || true
    fi
    cp -r server.py config.yaml dist/data
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
	# Word-splitting on $services is intentional: one --services arg per ARN.
	if ! aws ecs wait services-stable --cluster "$cluster" --services $services --region "$region"; then
		echo "ECS services did not reach a stable state"
		return 1
	fi
	echo "ECS services are stable and serving traffic."
}

create_deployment_package $1

terraform init
terraform apply

wait_for_ecs_stable