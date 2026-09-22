#!/bin/bash
set -eo pipefail # exit if any command in this script fails

# All three Lambdas deploy as container images built and pushed by Terraform itself (package_type
# = "Image", package_path pointing at each dist_* directory via the module's own
# yaalalabs/ak-common/aws//modules/ecr submodule), so Docker must be running but no manual
# docker/ECR/S3 steps are needed here — just build each dist_* directory and run terraform apply.
#
# Pass `local` as the first argument to install agentkernel from ../../../ak-py/dist instead of PyPI.

create_request_handler_deployment_package() {
	echo "Creating request handler deployment package..."
	pushd ../
	rm -rf dist_request_handler
	mkdir -p dist_request_handler/data
	uv export --extra request_handler --no-hashes >requirements.txt
	if [[ ${LOCAL_BUILD-} != "local" ]]; then
		uv pip install -r requirements.txt --target=dist_request_handler/data
	else
		uv pip install --force-reinstall --target=dist_request_handler/data --find-links ../../../ak-py/dist "agentkernel[aws,redis]" --no-cache-dir
	fi
	cp -r lambda_request_handler.py config.yaml dist_request_handler/data
	popd || exit 1
	cp Dockerfile.request_handler ../dist_request_handler/Dockerfile
}

# Runs the agent, so it's the only tier that needs the (heavy) OpenAI Agents SDK — see the
# `agent_runner` extra in pyproject.toml.
create_agent_runner_deployment_package() {
	echo "Creating agent runner deployment package..."
	pushd ../
	rm -rf dist_agent_runner
	mkdir -p dist_agent_runner/data
	uv export --extra agent_runner --no-hashes >requirements.txt
	if [[ ${LOCAL_BUILD-} != "local" ]]; then
		uv pip install -r requirements.txt --target=dist_agent_runner/data
	else
		uv pip install --force-reinstall --target=dist_agent_runner/data --find-links ../../../ak-py/dist "agentkernel[aws,openai,redis]" --no-cache-dir
	fi
	cp -r lambda_agent_runner.py config.yaml dist_agent_runner/data
	popd || exit 1
	cp Dockerfile.agent_runner ../dist_agent_runner/Dockerfile
}

create_response_handler_deployment_package() {
	echo "Creating response handler deployment package..."
	pushd ../
	rm -rf dist_response_handler
	mkdir -p dist_response_handler/data
	uv export --extra response_handler --no-hashes >requirements.txt
	if [[ ${LOCAL_BUILD-} != "local" ]]; then
		uv pip install -r requirements.txt --target=dist_response_handler/data
	else
		uv pip install --force-reinstall --target=dist_response_handler/data --find-links ../../../ak-py/dist "agentkernel[aws,redis]" --no-cache-dir
	fi
	cp -r lambda_response_handler.py config.yaml dist_response_handler/data
	popd || exit 1
	cp Dockerfile.response_handler ../dist_response_handler/Dockerfile
}

LOCAL_BUILD=${1-}

create_request_handler_deployment_package
create_agent_runner_deployment_package
create_response_handler_deployment_package

rm -f ../requirements.txt

terraform init
terraform apply
