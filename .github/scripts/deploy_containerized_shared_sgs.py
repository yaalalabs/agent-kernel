#!/usr/bin/env python3
"""
Apply the shared aws-containerized security group stack and output its IDs.

The stack (.github/ci-infra/aws-containerized-shared-sgs) is long-lived and never destroyed by CI:
`terraform apply` is a no-op when the security groups already exist and recreates them if they were
deleted. The ALB, ECS service and agent runner security group IDs are written to $GITHUB_OUTPUT so
the weekly aws-containerized matrix jobs reuse them instead of creating their own (#823).
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


def read_region(deploy_path: Path) -> str | None:
    """Read `region` from the base deployment's terraform.tfvars."""
    tfvars = deploy_path / "terraform.tfvars"
    if not tfvars.exists():
        return None
    match = re.search(r'^\s*region\s*=\s*"([^"]+)"', tfvars.read_text(), re.M)
    return match.group(1) if match else None


OUTPUT_NAMES = [
    "alb_security_group_id",
    "ecs_service_security_group_id",
    "agent_runner_security_group_id",
]


def main():
    parser = argparse.ArgumentParser(
        description="Apply the shared aws-containerized security groups and output their IDs"
    )
    parser.add_argument(
        "--stack-path",
        default=".github/ci-infra/aws-containerized-shared-sgs",
        help="Path to the shared security group Terraform stack",
    )
    parser.add_argument("--vpc-id", required=True, help="VPC ID from the base deployment")
    parser.add_argument(
        "--base-path",
        default="examples/aws-serverless/openai",
        help="Path to the base deployment project; the SGs are created in its VPC's region",
    )
    parser.add_argument(
        "--deploy-dir",
        default="deploy",
        help="Deploy directory within the base path",
    )
    args = parser.parse_args()

    stack_path = Path(args.stack_path)
    if not stack_path.exists():
        print(f"Error: Shared security group stack not found: {stack_path}")
        sys.exit(1)
    # The base VPC lives in the region from the base deployment's terraform.tfvars, which is not
    # necessarily the workflow's AWS_REGION (that one only scopes the credentials).
    region = read_region(Path(args.base_path) / args.deploy_dir)
    if not region:
        print(f"Error: Could not read region from {Path(args.base_path) / args.deploy_dir}/terraform.tfvars")
        sys.exit(1)

    tf_env = {
        **os.environ,
        "TF_INPUT": "0",
        "TF_VAR_vpc_id": args.vpc_id,
        "TF_VAR_region": region,
    }

    print(f"Initializing Terraform in {stack_path}...")
    subprocess.run(["terraform", "init", "-upgrade"], cwd=str(stack_path), check=True, env=tf_env)

    print(f"Applying shared security groups in VPC {args.vpc_id} ({region})...")
    subprocess.run(["terraform", "apply", "-auto-approve", "-lock-timeout=5m"], cwd=str(stack_path), check=True, env=tf_env)

    outputs = {}
    for name in OUTPUT_NAMES:
        result = subprocess.run(
            ["terraform", "output", "-raw", name],
            cwd=str(stack_path),
            check=True,
            capture_output=True,
            text=True,
            env=tf_env,
        )
        outputs[name] = result.stdout.strip()
        print(f"{name}: {outputs[name]}")

    # Write to GitHub Actions output, prefixed so they don't clash with the serverless base's
    # agent_runner_security_group_id among the get-base-outputs job outputs
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with open(github_output, "a") as f:
            for name, value in outputs.items():
                f.write(f"containerized_{name}={value}\n")
        print("Outputs written to $GITHUB_OUTPUT")
    else:
        print("GITHUB_OUTPUT not set — printing outputs only")


if __name__ == "__main__":
    main()
