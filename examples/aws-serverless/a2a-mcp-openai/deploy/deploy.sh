#!/bin/bash
set -eo pipefail # exit if any command in this script fails

# The response handler and the authorizer deploy as local zips. The request handler and the agent runner deploy as
# container images: both load the OpenAI Agents SDK (the request handler to build the A2A cards and the MCP tools from
# the agents it registers), which does not fit inside Lambda's 250 MB unzipped zip limit. Terraform builds and pushes
# the images from ../dist_request_handler and ../dist_agent_runner, so Docker must be running.
#
# Pass `local` as the first argument to use the branch you are on:
#   - install agentkernel from ../../../ak-py/dist instead of PyPI, and
#   - use the Terraform module from ../../../../ak-deployment/ak-aws/serverless instead of the registry's. The
#     enable_a2a_server and enable_mcp_server inputs this example uses ship with the module release after 0.10.2,
#     so until it is published the registry module has no such input.
LAMBDA_TARGET=(--python-platform x86_64-manylinux_2_34 --python-version 3.12 --only-binary :all:)

install_lambda_dependencies() {
	local extra="$1" target="$2" local_extras="$3"
	uv export --extra "$extra" --no-hashes --no-dev >requirements.txt
	if [[ ${LOCAL_BUILD-} != "local" ]]; then
		uv pip install -r requirements.txt --target="$target" "${LAMBDA_TARGET[@]}"
	else
		uv pip install --force-reinstall --target="$target" --find-links ../../../ak-py/dist "agentkernel[$local_extras]" --no-cache-dir "${LAMBDA_TARGET[@]}"
	fi
}

# $1 = the pyproject extra, $2 = the entrypoint file(s), $3 = the dist directory name,
# $4 = the extras to force-reinstall from the local ak-py dist.
create_zip_deployment_package() {
	local extra="$1" entrypoints="$2" dist="$3" local_extras="$4"
	echo "Creating $dist deployment package (zip mode, extra: $extra)..."
	pushd ../
	rm -rf "$dist" "$dist.zip"
	mkdir -p "$dist"
	install_lambda_dependencies "$extra" "$dist" "$local_extras"
	# shellcheck disable=SC2086 # $entrypoints is a space-separated list of file names
	cp -r $entrypoints config.yaml "$dist/"
	cd "$dist" && zip -rq "../$dist.zip" .
	popd || exit 1
}

# $1 = the pyproject extra, $2 = the entrypoint file(s), $3 = the dist directory name,
# $4 = the extras to force-reinstall from the local ak-py dist, $5 = the Dockerfile to build it with.
# The dependencies and the entrypoints go into data/, which the Dockerfile copies to /var/task.
create_image_deployment_package() {
	local extra="$1" entrypoints="$2" dist="$3" local_extras="$4" dockerfile="$5"
	echo "Creating $dist deployment package (image mode, extra: $extra)..."
	pushd ../
	rm -rf "$dist"
	mkdir -p "$dist/data"
	install_lambda_dependencies "$extra" "$dist/data" "$local_extras"
	# shellcheck disable=SC2086
	cp -r $entrypoints config.yaml "$dist/data"
	popd || exit 1
	cp "$dockerfile" "../$dist/Dockerfile"
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

# `local` points the module at this checkout through an override file (gitignored), so main.tf keeps the registry
# source and version the release process bumps. Without `local` the override is removed.
if [[ $LOCAL_BUILD == "local" ]]; then
	cat >zz_local_module_override.tf <<'OVERRIDE'
# Written by deploy.sh local: use the Terraform module from this checkout instead of the registry's.
module "serverless_agents" {
  source  = "../../../../ak-deployment/ak-aws/serverless"
  version = null
}
OVERRIDE
else
	rm -f zz_local_module_override.tf
fi

create_image_deployment_package request_handler "lambda_request_handler.py lambda_agents.py" dist_request_handler "aws,openai,a2a,mcp" Dockerfile.request_handler
create_image_deployment_package agent_runner "lambda_agent_runner.py lambda_agents.py" dist_agent_runner "aws,openai" Dockerfile.agent_runner
create_zip_deployment_package response_handler lambda_response_handler.py dist_response_handler "aws"
create_zip_deployment_package authorizer lambda_auth.py dist_auth "aws"

echo "Package sizes:"
report_zip_size dist_response_handler
report_zip_size dist_auth
echo "  dist_request_handler: $(du -sh ../dist_request_handler | cut -f1) image build context"
echo "  dist_agent_runner: $(du -sh ../dist_agent_runner | cut -f1) image build context"

rm -f ../requirements.txt

# The agent card advertises the API's public URL, and MCP's login metadata names it, so the request handler needs it as
# a2a.url / mcp.url. It contains the API's id, which exists only once the API does: apply once without it, read it from
# the output, and apply again (the second apply changes the request handler's environment only). It is kept in
# public_url.auto.tfvars so a later plain `terraform apply` does not lose it; a fresh deployment starts without one.
terraform init
terraform apply
echo "public_base_url = \"$(terraform output -raw public_base_url)\"" >public_url.auto.tfvars
echo "Telling the request handler its public URL ($(terraform output -raw public_base_url))..."
terraform apply
