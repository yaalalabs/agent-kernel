#!/bin/bash

set -e

create_deployment_packages() {
    pushd ../

    uv export --no-hashes > requirements.txt

    # REST Service dist
    rm -rf dist-rest-service
    mkdir -p dist-rest-service/data
    if [[ ${1-} != "local" ]]; then
        uv pip install -r requirements.txt --target=dist-rest-service/data
    else
        uv pip install -r requirements.txt --target=dist-rest-service/data --find-links ../../../ak-py/dist --upgrade-package agentkernel
    fi
	cp config.yaml app_rest_service.py dist-rest-service/data/

    # Agent Runner dist
    rm -rf dist-agent-runner
    mkdir -p dist-agent-runner/data
    if [[ ${1-} != "local" ]]; then
        uv pip install -r requirements.txt --target=dist-agent-runner/data
    else
        uv pip install -r requirements.txt --target=dist-agent-runner/data --find-links ../../../ak-py/dist --upgrade-package agentkernel
    fi
    cp config.yaml app_agent_runner.py dist-agent-runner/data/

    rm -f requirements.txt
    popd || exit 1

    # Copy Dockerfiles into dist directories (must run from deploy/ after popd)
    cp Dockerfile.rest-service ../dist-rest-service/Dockerfile
    cp Dockerfile.agent-runner ../dist-agent-runner/Dockerfile
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

pushd ../../../../ak-py || exit 1
rm -rf dist
./build.sh local
popd

create_deployment_packages $1

terraform init
terraform apply

wait_for_ecs_stable
