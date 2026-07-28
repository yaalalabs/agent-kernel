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
        uv pip install -r requirements.txt --target=dist-rest-service/data --find-links ../../../ak-py/dist
        uv pip install --force-reinstall --target=dist-rest-service/data --find-links ../../../ak-py/dist agentkernel[adk,api,aws,test]
    fi
	cp config.yaml app_rest_service.py dist-rest-service/data/

    # Agent Runner dist
    rm -rf dist-agent-runner
    mkdir -p dist-agent-runner/data
    if [[ ${1-} != "local" ]]; then
        uv pip install -r requirements.txt --target=dist-agent-runner/data
    else
        uv pip install -r requirements.txt --target=dist-agent-runner/data --find-links ../../../ak-py/dist
        uv pip install --force-reinstall --target=dist-agent-runner/data --find-links ../../../ak-py/dist agentkernel[adk,api,aws,test]
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
	local region product_alias env_alias module_name cluster service
	region=$(read_tfvar region)
	product_alias=$(read_tfvar product_alias)
	env_alias=$(read_tfvar env_alias)
	module_name=$(read_tfvar module_name)
	cluster="${product_alias}-${env_alias}-${module_name}"

	echo "Resolving ECS service in cluster '${cluster}' (region ${region})..."
	service=$(aws ecs list-services --cluster "$cluster" --region "$region" \
		--query 'serviceArns[0]' --output text)
	if [[ -z "$service" || "$service" == "None" ]]; then
		echo "Could not find an ECS service in cluster '${cluster}'"
		return 1
	fi

	echo "Waiting for ECS service to become stable: ${service}"
	aws ecs wait services-stable --cluster "$cluster" --services "$service" --region "$region"
	echo "ECS service is stable and serving traffic."
}

pushd ../../../../ak-py || exit 1
rm -rf dist
./build.sh local
popd

create_deployment_packages $1

terraform init
terraform apply

wait_for_ecs_stable
