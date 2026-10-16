#!/bin/bash
set -eo pipefail # exit if any command in this script fails

# The request handler and the agent runner deploy as container images: the request handler carries the
# Opik judges and the agent runner the OpenAI Agents SDK, and neither fits inside Lambda's 250 MB unzipped
# zip limit. Terraform builds and pushes both images from ../dist_request_handler and ../dist_agent_runner,
# so Docker must be running. The response handler deploys as a local zip.
#
# Pass `local` as the first argument to install agentkernel from ../../../ak-py/dist instead of PyPI. The
# local wheel is force-reinstalled with --no-index: it carries the same version as a published release, and
# the example needs the local code (Trace.fetch, the Langfuse flush on Lambda).
#
# Packages are installed with --compile-bytecode: uv skips the .pyc files by default, and Lambda's read-only
# /var/task would make every cold start compile each imported module again.

create_request_handler_deployment_package() {
	echo "Creating request handler deployment package..."
	pushd ../
	rm -rf dist_request_handler
	mkdir -p dist_request_handler/data
	uv export --extra request_handler --no-dev --no-hashes >requirements.txt
	uv pip install --compile-bytecode -r requirements.txt --target=dist_request_handler/data
	if [[ ${LOCAL_BUILD-} == "local" ]]; then
		uv pip install --compile-bytecode --force-reinstall --no-deps --no-index --target=dist_request_handler/data --find-links ../../../ak-py/dist agentkernel
	fi
	cp -r lambda_request_handler.py config.yaml evaluator dist_request_handler/data
	popd || exit 1
	cp Dockerfile.request_handler ../dist_request_handler/Dockerfile
}

create_agent_runner_deployment_package() {
	echo "Creating agent runner deployment package..."
	pushd ../
	rm -rf dist_agent_runner
	mkdir -p dist_agent_runner/data
	uv export --extra agent_runner --no-dev --no-hashes >requirements.txt
	uv pip install --compile-bytecode -r requirements.txt --target=dist_agent_runner/data
	if [[ ${LOCAL_BUILD-} == "local" ]]; then
		uv pip install --compile-bytecode --force-reinstall --no-deps --no-index --target=dist_agent_runner/data --find-links ../../../ak-py/dist agentkernel
	fi
	cp -r lambda_agent_runner.py config.yaml dist_agent_runner/data
	popd || exit 1
	cp Dockerfile.agent_runner ../dist_agent_runner/Dockerfile
}

create_response_handler_deployment_package() {
	echo "Creating response handler deployment package..."
	pushd ../
	rm -rf dist_response_handler dist_response_handler.zip
	mkdir -p dist_response_handler
	uv export --extra response_handler --no-dev --no-hashes >requirements.txt
	uv pip install --compile-bytecode -r requirements.txt --target=dist_response_handler
	if [[ ${LOCAL_BUILD-} == "local" ]]; then
		uv pip install --compile-bytecode --force-reinstall --no-deps --no-index --target=dist_response_handler --find-links ../../../ak-py/dist agentkernel
	fi
	cp -r lambda_response_handler.py config.yaml dist_response_handler/
	cd dist_response_handler && zip -rq ../dist_response_handler.zip .
	popd || exit 1
}

LOCAL_BUILD=${1-}

create_request_handler_deployment_package
create_agent_runner_deployment_package
create_response_handler_deployment_package

rm -f ../requirements.txt

terraform init
terraform apply
