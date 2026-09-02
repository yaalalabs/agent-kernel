#!/bin/bash
set -e
load_env() {
	if [[ -f "../.env" ]]; then
		echo "Loading variables from ../.env"
		set -a
		source "../.env"
		set +a
	fi
	map_tf_var TF_VAR_openai_api_key "${OPENAI_API_KEY-}"
	map_tf_var TF_VAR_slack_bot_token "${SLACK_BOT_TOKEN-}"
	map_tf_var TF_VAR_slack_signing_secret "${SLACK_SIGNING_SECRET-}"
	map_tf_var TF_VAR_telegram_bot_token "${TELEGRAM_BOT_TOKEN-}"
	map_tf_var TF_VAR_telegram_webhook_secret "${TELEGRAM_WEBHOOK_SECRET-}"
	map_tf_var TF_VAR_gmail_client_id "${GMAIL_CLIENT_ID-}"
	map_tf_var TF_VAR_gmail_client_secret "${GMAIL_CLIENT_SECRET-}"
	map_tf_var TF_VAR_gmail_token_b64 "${GMAIL_TOKEN_B64-}"
	map_tf_var TF_VAR_gmail_sender_filter "${GMAIL_SENDER_FILTER-}"
	map_tf_var TF_VAR_whatsapp_access_token "${WHATSAPP_ACCESS_TOKEN-}"
	map_tf_var TF_VAR_whatsapp_phone_number_id "${WHATSAPP_PHONE_NUMBER_ID-}"
	map_tf_var TF_VAR_whatsapp_verify_token "${WHATSAPP_VERIFY_TOKEN-}"
	map_tf_var TF_VAR_whatsapp_app_secret "${WHATSAPP_APP_SECRET-}"
	map_tf_var TF_VAR_messenger_access_token "${MESSENGER_ACCESS_TOKEN-}"
	map_tf_var TF_VAR_messenger_verify_token "${MESSENGER_VERIFY_TOKEN-}"
	map_tf_var TF_VAR_messenger_app_secret "${MESSENGER_APP_SECRET-}"
	map_tf_var TF_VAR_instagram_access_token "${INSTAGRAM_ACCESS_TOKEN-}"
	map_tf_var TF_VAR_instagram_verify_token "${INSTAGRAM_VERIFY_TOKEN-}"
	map_tf_var TF_VAR_instagram_app_secret "${INSTAGRAM_APP_SECRET-}"
	map_tf_var TF_VAR_instagram_account_id "${INSTAGRAM_ACCOUNT_ID-}"
}

map_tf_var() {
	local tf_name="$1" value="$2"
	if [[ -z "${!tf_name-}" && -n "$value" ]]; then
		export "$tf_name=$value"
	fi
}

create_deployment_package() {
    pushd ../
    rm -rf dist
    mkdir -p dist/data
    uv export --no-hashes --no-dev > requirements.txt
    if [[ ${1-} != "local" ]]; then
      uv pip install -r requirements.txt --target=dist/data
    else
      uv pip install -r requirements.txt --target=dist/data --find-links ../../ak-py/dist --upgrade-package agentkernel
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
	# Word-splitting on $services is intentional: one --services arg per ARN.
	if ! aws ecs wait services-stable --cluster "$cluster" --services $services --region "$region"; then
		echo "ECS services did not reach a stable state"
		return 1
	fi
	echo "ECS services are stable and serving traffic."
}

load_env

create_deployment_package $1

terraform init
terraform apply

wait_for_ecs_stable
