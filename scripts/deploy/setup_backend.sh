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
if aws s3 ls "s3://$BUCKET_NAME" 2>&1 | grep -q 'NoSuchBucket'; then
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
    echo "S3 bucket already exists"
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
