#!/bin/bash

# OPTIONAL: This script sets up S3 backend for Terraform state management
# 
# This script creates:
# - An S3 bucket for storing Terraform state
# - A DynamoDB table for state locking
#
# You can safely skip running this script if you prefer to use local state
# or if you already have backend infrastructure set up.
#
# Usage: ./setup_backend.sh [bucket-name] [dynamodb-table-name] [region]
# Example: ./setup_backend.sh my-terraform-state terraform-lock us-east-1
# If no arguments provided, defaults will be used

set -e

# Set defaults
BUCKET_NAME=${1:-agent-kernel-terraform-state-bucket}
DYNAMODB_TABLE=${2:-ak-terraform-state-lock}
REGION=${3:-ap-southeast-2}

echo "Setting up Terraform backend infrastructure..."
echo "Bucket: $BUCKET_NAME"
echo "DynamoDB Table: $DYNAMODB_TABLE"
echo "Region: $REGION"

# Create S3 bucket for state storage
echo "Creating S3 bucket..."
if aws s3api head-bucket --bucket "$BUCKET_NAME" --region "$REGION" >/dev/null 2>&1; then
    # Bucket exists and is accessible
    echo "S3 bucket already exists"
else
    # Re-run head-bucket to capture the error message for analysis without causing the script to exit
    bucket_check_error=$(aws s3api head-bucket --bucket "$BUCKET_NAME" --region "$REGION" 2>&1 || true)

    if echo "$bucket_check_error" | grep -qiE 'NoSuchBucket|Not Found'; then
        aws s3api create-bucket \
            --bucket "$BUCKET_NAME" \
            --region "$REGION" \
            $(if [ "$REGION" != "us-east-1" ]; then echo "--create-bucket-configuration LocationConstraint=$REGION"; fi)

        # Enable versioning
        aws s3api put-bucket-versioning \
            --bucket "$BUCKET_NAME" \
            --versioning-configuration Status=Enabled

        # Enable encryption
        aws s3api put-bucket-encryption \
            --bucket "$BUCKET_NAME" \
            --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

        echo "S3 bucket created successfully"
    else
        echo "Error checking S3 bucket \"$BUCKET_NAME\": $bucket_check_error" >&2
        echo "Aborting backend setup to avoid creating a bucket when the real issue may be permissions or another error." >&2
        exit 1
    fi
fi

# Create DynamoDB table for state locking
echo "Creating DynamoDB table..."
if ! aws dynamodb describe-table --table-name "$DYNAMODB_TABLE" --region "$REGION" 2>&1 | grep -q "TableName"; then
    aws dynamodb create-table \
        --table-name "$DYNAMODB_TABLE" \
        --attribute-definitions AttributeName=LockID,AttributeType=S \
        --key-schema AttributeName=LockID,KeyType=HASH \
        --provisioned-throughput ReadCapacityUnits=5,WriteCapacityUnits=5 \
        --region "$REGION"
    
    echo "Waiting for DynamoDB table to be created..."
    aws dynamodb wait table-exists --table-name "$DYNAMODB_TABLE" --region "$REGION"
    echo "DynamoDB table created successfully"
else
    echo "DynamoDB table already exists"
fi

echo ""
echo "✅ Backend infrastructure setup complete!"
echo ""
echo "You can now use this backend configuration in your backend.tf:"
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
