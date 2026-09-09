#!/bin/bash
set -eo pipefail # exit if any command in this script fails

# The request and response handlers deploy as local zips; the agent runner deploys as a container
# image because agentkernel[aws,openai,cron] (the OpenAI Agents SDK in particular) does not fit
# inside Lambda's 250 MB unzipped zip limit. Terraform builds and pushes that image from
# ../dist_agent_runner, so Docker must be running.
#
# Pass `local` as the first argument to install agentkernel from ../../../ak-py/dist instead of PyPI.

# $1 = the pyproject extra, $2 = the entrypoint module, $3 = the dist directory name,
# $4 = the extras to force-reinstall from the local ak-py dist.
create_zip_deployment_package() {
	local extra="$1" entrypoint="$2" dist="$3" local_extras="$4"
	echo "Creating $dist deployment package (zip mode, extra: $extra)..."
	pushd ../
	rm -rf "$dist" "$dist.zip"
	mkdir -p "$dist"
	uv export --extra "$extra" --no-hashes >requirements.txt
	if [[ ${LOCAL_BUILD-} != "local" ]]; then
		uv pip install -r requirements.txt --target="$dist"
	else
		uv pip install --force-reinstall --target="$dist" --find-links ../../../ak-py/dist "agentkernel[$local_extras]" --no-cache-dir
	fi
	cp -r "$entrypoint" config.yaml "$dist/"
	cd "$dist" && zip -rq "../$dist.zip" .
	popd || exit 1
}

# $1 = the pyproject extra, $2 = the entrypoint module, $3 = the dist directory name,
# $4 = the extras to force-reinstall from the local ak-py dist.
# The dependencies and the entrypoint go into data/, which the Dockerfile copies to /var/task.
create_image_deployment_package() {
	local extra="$1" entrypoint="$2" dist="$3" local_extras="$4"
	echo "Creating $dist deployment package (image mode, extra: $extra)..."
	pushd ../
	rm -rf "$dist"
	mkdir -p "$dist/data"
	uv export --extra "$extra" --no-hashes >requirements.txt
	if [[ ${LOCAL_BUILD-} != "local" ]]; then
		uv pip install -r requirements.txt --target="$dist/data"
	else
		uv pip install --force-reinstall --target="$dist/data" --find-links ../../../ak-py/dist "agentkernel[$local_extras]" --no-cache-dir
	fi
	cp -r "$entrypoint" config.yaml "$dist/data"
	popd || exit 1
	cp Dockerfile.agent_runner "../$dist/Dockerfile"
}

report_zip_size() {
	# Lambda's hard limit for a zip-deployed function is 250 MB unzipped.
	local dist="$1"
	local unzipped
	unzipped=$(du -sm "../$dist" | cut -f1)
	echo "  $dist: $(du -h "../$dist.zip" | cut -f1) zipped, ${unzipped} MB unzipped"
	if ((unzipped > 250)); then
		echo "  WARNING: $dist exceeds Lambda's 250 MB unzipped limit. Move dependencies into a Lambda" >&2
		echo "           layer or switch this function to package_type = \"Image\" like the agent runner." >&2
	fi
}

LOCAL_BUILD=${1-}

create_zip_deployment_package request_handler lambda_request_handler.py dist_request_handler "aws,cron"
create_image_deployment_package agent_runner lambda_agent_runner.py dist_agent_runner "aws,openai,cron"
create_zip_deployment_package response_handler lambda_response_handler.py dist_response_handler "aws"

echo "Package sizes:"
report_zip_size dist_request_handler
report_zip_size dist_response_handler
echo "  dist_agent_runner: $(du -sh ../dist_agent_runner | cut -f1) image build context"

rm -f ../requirements.txt

terraform init
terraform apply
