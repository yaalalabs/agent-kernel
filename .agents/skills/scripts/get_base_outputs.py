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
    subprocess.run(
        ["terraform", "init", "-upgrade"],
        cwd=str(deploy_path),
        check=True,
        env={**os.environ, "TF_INPUT": "0"},
    )

    # Retrieve vpc_id
    result = subprocess.run(
        ["terraform", "output", "-raw", "vpc_id"],
        cwd=str(deploy_path),
        check=True,
        capture_output=True,
        text=True,
    )
    vpc_id = result.stdout.strip()

    # Retrieve private_subnet_ids (JSON array)
    result = subprocess.run(
        ["terraform", "output", "-json", "private_subnet_ids"],
        cwd=str(deploy_path),
        check=True,
        capture_output=True,
        text=True,
    )
    private_subnet_ids = result.stdout.strip()

    # Validate
    json.loads(private_subnet_ids)  # ensure valid JSON

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
