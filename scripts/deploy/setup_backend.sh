#!/usr/bin/env bash

set -euo pipefail

CUR_SCRIPT=$(readlink -f ${BASH_SOURCE[0]})
CUR_SCRIPT_DIR=$(dirname $CUR_SCRIPT)
CUR_FOLDER=$(basename $CUR_SCRIPT_DIR)

CONFIG_FILE="$CUR_SCRIPT_DIR/state-config.yaml"
CLOUD="${1:-aws}"

if ! command -v yq >/dev/null 2>&1; then
	echo "❌ yq is required (https://github.com/mikefarah/yq)"
	exit 1
fi

function help() {
	cat <<EOF
Terraform Backend Setup Script (Multi-Cloud)

Usage:
  $(basename "$0") <cloud> [options]

Clouds:
  aws       Setup S3 + DynamoDB backend
  azure     Setup Azure Storage backend
  gcp       Setup GCS backend

Options:

  AWS options:
    --bucket <name>           S3 bucket name
    --dynamodb <name>         DynamoDB table name
    --region <region>         AWS region

  Azure options:
    --storage <name>          Storage account name
    --container <name>        Blob container name
    --resource-group <name>   Resource group name

General:
    -h, --help                Show this help message

Config:
  Defaults are loaded from:
    state-config.yaml (in script directory)

  Override priority:
    CLI args > YAML config

Examples:

  # Use defaults from YAML
  $(basename "$0") aws

  # Override AWS values
  $(basename "$0") aws \
    --bucket my-tf-state \
    --dynamodb my-lock-table \
    --region us-east-1

  # Azure with overrides
  $(basename "$0") azure \
    --storage mystorageacct \
    --container tfstate \
    --resource-group my-rg

Notes:
  - Requires:
      * aws CLI (for AWS)
      * az CLI (for Azure)
      * yq (for YAML parsing)
  - Make sure you're authenticated before running.

EOF
}

########################################
# AWS SETUP
########################################
setup_aws() {
	BUCKET_NAME=${BUCKET_NAME:-$(yq e '.aws.state.bucket_name' "$CONFIG_FILE")}
	DYNAMODB_TABLE=${DYNAMODB_TABLE:-$(yq e '.aws.state.dynamodb_table' "$CONFIG_FILE")}
	REGION=${REGION:-$(yq e '.aws.state.region' "$CONFIG_FILE")}

	echo "Setting up AWS backend..."
	echo "Bucket: $BUCKET_NAME"
	echo "DynamoDB Table: $DYNAMODB_TABLE"
	echo "Region: $REGION"

	# S3 bucket
	if aws s3api head-bucket --bucket "$BUCKET_NAME" --region "$REGION" >/dev/null 2>&1; then
		echo "S3 bucket already exists"
	else
		echo "Creating S3 bucket..."
		aws s3api create-bucket \
			--bucket "$BUCKET_NAME" \
			--region "$REGION" \
			$(if [ "$REGION" != "us-east-1" ]; then echo "--create-bucket-configuration LocationConstraint=$REGION"; fi)

		aws s3api put-bucket-versioning \
			--bucket "$BUCKET_NAME" \
			--versioning-configuration Status=Enabled

		aws s3api put-bucket-encryption \
			--bucket "$BUCKET_NAME" \
			--server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

		echo "S3 bucket created"
	fi

	# DynamoDB
	if aws dynamodb describe-table --table-name "$DYNAMODB_TABLE" --region "$REGION" >/dev/null 2>&1; then
		echo "DynamoDB table exists"
	else
		echo "Creating DynamoDB table..."
		aws dynamodb create-table \
			--table-name "$DYNAMODB_TABLE" \
			--attribute-definitions AttributeName=LockID,AttributeType=S \
			--key-schema AttributeName=LockID,KeyType=HASH \
			--provisioned-throughput ReadCapacityUnits=5,WriteCapacityUnits=5 \
			--region "$REGION"

		aws dynamodb wait table-exists --table-name "$DYNAMODB_TABLE" --region "$REGION"
		echo "DynamoDB table created"
	fi

	echo ""
	echo "terraform {"
	echo "  backend \"s3\" {"
	echo "    bucket         = \"$BUCKET_NAME\""
	echo "    key            = \"your-project/terraform.tfstate\""
	echo "    region         = \"$REGION\""
	echo "    dynamodb_table = \"$DYNAMODB_TABLE\""
	echo "    encrypt        = true"
	echo "  }"
	echo "}"
}

########################################
# AZURE SETUP
########################################
setup_azure() {
	STORAGE_ACCOUNT=${STORAGE_ACCOUNT:-$(yq e '.azure.state.storage_account' "$CONFIG_FILE")}
	CONTAINER_NAME=${CONTAINER_NAME:-$(yq e '.azure.state.container_name' "$CONFIG_FILE")}
	RESOURCE_GROUP=${RESOURCE_GROUP:-$(yq e '.azure.state.resource_group' "$CONFIG_FILE")}

	echo "Setting up Azure backend..."
	echo "Storage Account: $STORAGE_ACCOUNT"
	echo "Container: $CONTAINER_NAME"
	echo "Resource Group: $RESOURCE_GROUP"

	# Create resource group if not exists
	if az group show --name "$RESOURCE_GROUP" >/dev/null 2>&1; then
		echo "Resource group exists"
	else
		echo "Creating resource group..."
		az group create --name "$RESOURCE_GROUP" --location "eastus"
	fi

	# Create storage account
	if az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
		echo "Storage account exists"
	else
		echo "Creating storage account..."
		az storage account create \
			--name "$STORAGE_ACCOUNT" \
			--resource-group "$RESOURCE_GROUP" \
			--sku Standard_LRS \
			--encryption-services blob
	fi

	# Get key
	ACCOUNT_KEY=$(az storage account keys list \
		--resource-group "$RESOURCE_GROUP" \
		--account-name "$STORAGE_ACCOUNT" \
		--query '[0].value' -o tsv)

	# Create container
	if az storage container show \
		--name "$CONTAINER_NAME" \
		--account-name "$STORAGE_ACCOUNT" \
		--account-key "$ACCOUNT_KEY" >/dev/null 2>&1; then
		echo "Container exists"
	else
		echo "Creating container..."
		az storage container create \
			--name "$CONTAINER_NAME" \
			--account-name "$STORAGE_ACCOUNT" \
			--account-key "$ACCOUNT_KEY"
	fi

	echo ""
	echo "terraform {"
	echo "  backend \"azurerm\" {"
	echo "    resource_group_name  = \"$RESOURCE_GROUP\""
	echo "    storage_account_name = \"$STORAGE_ACCOUNT\""
	echo "    container_name       = \"$CONTAINER_NAME\""
	echo "    key                  = \"your-project/terraform.tfstate\""
	echo "  }"
	echo "}"
}

########################################
# GCP SETUP
########################################
setup_gcp() {
	GCP_BUCKET=${GCP_BUCKET:-$(yq e '.gcp.state.bucket_name' "$CONFIG_FILE")}
	GCP_PROJECT=${GCP_PROJECT:-$(yq e '.gcp.state.project_id' "$CONFIG_FILE")}
	GCP_REGION=${GCP_REGION:-$(yq e '.gcp.state.region' "$CONFIG_FILE")}

	echo "Setting up GCP backend..."
	echo "Bucket: $GCP_BUCKET"
	echo "Project: $GCP_PROJECT"
	echo "Region: $GCP_REGION"

	# Check bucket
	if gcloud storage buckets describe "gs://$GCP_BUCKET" --project "$GCP_PROJECT" >/dev/null 2>&1; then
		echo "GCS bucket exists"
	else
		echo "Creating GCS bucket..."

		gcloud storage buckets create "gs://$GCP_BUCKET" \
			--project="$GCP_PROJECT" \
			--location="$GCP_REGION" \
			--uniform-bucket-level-access

		echo "Enabling versioning..."
		gcloud storage buckets update "gs://$GCP_BUCKET" \
			--versioning

		echo "GCS bucket created"
	fi

	echo ""
	echo "terraform {"
	echo "  backend \"gcs\" {"
	echo "    bucket = \"$GCP_BUCKET\""
	echo "    prefix = \"$GCP_PROJECT\""
	echo "  }"
	echo "}"
}

########################################
# MAIN
########################################
# Default override variables (empty)
BUCKET_NAME=""
DYNAMODB_TABLE=""
REGION=""

STORAGE_ACCOUNT=""
CONTAINER_NAME=""
RESOURCE_GROUP=""



# Parse args
while [[ $# -gt 0 ]]; do
	case "$1" in
	aws | azure| gcp)
		CLOUD="$1"
		shift
		;;
	-h | --help)
		help
		exit 0
		;;
	--bucket)
		BUCKET_NAME="$2"
		GCP_BUCKET="$2"
		shift 2
		;;
	--region)
		REGION="$2"
		GCP_REGION="$2"
		shift 2
		;;
	--storage)
		STORAGE_ACCOUNT="$2"
		shift 2
		;;
	--container)
		CONTAINER_NAME="$2"
		shift 2
		;;
	--resource-group)
		RESOURCE_GROUP="$2"
		shift 2
		;;
	*)
		echo "Unknown argument: $1"
		help
		exit 1
		;;
	esac
done

echo "🌍 Selected cloud: $CLOUD"
echo "📄 Using config: $CONFIG_FILE"
echo ""

case "$CLOUD" in
aws)
	setup_aws
	;;
azure)
	setup_azure
	;;
gcp)
	setup_gcp
	;;
*)
	echo "Unsupported cloud: $CLOUD"
	echo "Supported: aws | azure | gcp"
	help
	;;
esac

echo ""
echo "Backend setup complete!"
