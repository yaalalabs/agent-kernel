#!/usr/bin/env python3
"""
Retrieve VPC and subnet outputs from the base deployment.

This script initializes Terraform in the base deployment directory and
retrieves the VPC ID and private subnet IDs. Results are written to
$GITHUB_OUTPUT for use in subsequent workflow steps.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Retrieve base deployment outputs (VPC ID, subnet IDs)"
    )
    parser.add_argument(
        "--base-path",
        default="examples/aws-serverless/openai",
        help="Path to the base deployment project",
    )
    parser.add_argument(
        "--deploy-dir",
        default="deploy",
        help="Deploy directory within the base path",
    )
    args = parser.parse_args()

    deploy_path = Path(args.base_path) / args.deploy_dir

    if not deploy_path.exists():
        print(f"Error: Base deployment path not found: {deploy_path}")
        sys.exit(1)

    # Initialize Terraform to access remote state
    print(f"Initializing Terraform in {deploy_path}...")
    try:
        subprocess.run(
            ["terraform", "init", "-upgrade"],
            cwd=str(deploy_path),
            check=True,
            env={**os.environ, "TF_INPUT": "0"},
        )
    except subprocess.CalledProcessError as e:
        print(f"Error: Terraform init failed with exit code {e.returncode}")
        sys.exit(1)

    # Wrap outputs in a try/except to handle missing state gracefully
    try:
        print("Fetching outputs from Terraform state...")
        
        # Retrieve vpc_id
        result_vpc = subprocess.run(
            ["terraform", "output", "-raw", "vpc_id"],
            cwd=str(deploy_path),
            check=True,
            capture_output=True,
            text=True,
        )
        vpc_id = result_vpc.stdout.strip()

        # Retrieve private_subnet_ids (JSON array)
        result_subnet = subprocess.run(
            ["terraform", "output", "-json", "private_subnet_ids"],
            cwd=str(deploy_path),
            check=True,
            capture_output=True,
            text=True,
        )
        private_subnet_ids = result_subnet.stdout.strip()

    except subprocess.CalledProcessError as e:
        print(f"\n❌ ERROR: Failed to retrieve Terraform outputs.")
        print(f"Command run: {' '.join(e.cmd)}")
        print(f"Terraform stderr: {e.stderr.strip() if e.stderr else 'No stderr output'}")
        print("\nPossible causes:")
        print("1. 'terraform apply' has not been run yet for the base deployment (no state file exists).")
        print("2. The outputs 'vpc_id' or 'private_subnet_ids' are not defined in the Terraform configuration.")
        sys.exit(1)

    # Validate JSON
    try:
        json.loads(private_subnet_ids)  # ensure valid JSON
    except json.JSONDecodeError:
        print(f"Error: private_subnet_ids is not valid JSON. Received: {private_subnet_ids}")
        sys.exit(1)

    print(f"VPC ID: {vpc_id}")
    print(f"Private Subnet IDs: {private_subnet_ids}")

    # Write to GitHub Actions output
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"vpc_id={vpc_id}\n")
            f.write(f"private_subnet_ids={private_subnet_ids}\n")
        print("Outputs written to $GITHUB_OUTPUT")
    else:
        print("GITHUB_OUTPUT not set — printing outputs only")


if __name__ == "__main__":
    main()