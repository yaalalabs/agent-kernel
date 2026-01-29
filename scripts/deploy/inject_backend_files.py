#!/usr/bin/env python3
"""
Inject Terraform backend configuration files into AWS example projects.

This script reads the integration test configuration to identify AWS projects
and injects backend.tf files into their deploy directories.

The backend.tf file is generated from a template with project-specific values.
These files are intended for CI/CD use and are marked as optional in comments.
"""

import os
import yaml
from pathlib import Path
from typing import List, Dict, Set


def load_config(config_path: str) -> Dict:
    """Load the integration test configuration YAML file."""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def get_aws_projects(config: Dict) -> Set[tuple]:
    """
    Extract AWS project paths from the configuration.
    
    Returns a set of tuples: (project_path, deploy_dir, project_type)
    """
    aws_projects = set()
    
    # Include deployment base infrastructure
    if 'deployment_base' in config:
        for project in config['deployment_base']:
            test_type = project.get('type', '')
            if test_type in ['aws-serverless', 'aws-containerized']:
                path = project.get('path', '')
                deploy_dir = project.get('deploy_dir', 'deploy')
                if path:
                    aws_projects.add((path, deploy_dir, test_type))
    
    # Process both nightly and weekly test configs
    for schedule in ['nightly', 'weekly']:
        if schedule in config and 'tests' in config[schedule]:
            for test in config[schedule]['tests']:
                test_type = test.get('type', '')
                if test_type in ['aws-serverless', 'aws-containerized']:
                    path = test.get('path', '')
                    deploy_dir = test.get('deploy_dir', 'deploy')
                    if path:
                        aws_projects.add((path, deploy_dir, test_type))
    
    return aws_projects


def generate_backend_tf(template_content: str, project_path: str, project_type: str) -> str:
    """
    Generate backend.tf content from template with project-specific values.
    
    Args:
        template_content: The template file content
        project_path: Path to the project (e.g., examples/aws-serverless/adk)
        project_type: Type of project (aws-serverless or aws-containerized)
    
    Returns:
        Generated backend.tf content
    """
    # Extract project name from path (e.g., "adk" from "examples/aws-serverless/adk")
    project_name = project_path.split('/')[-1]
    
    # Generate state key based on project path
    state_key = f"{project_path}/terraform.tfstate"
    
    # Use placeholder values - these should be configured per environment
    bucket_name = "agent-kernel-terraform-state-bucket"
    dynamodb_table = "ak-terraform-state-lock"
    region = "ap-southeast-2"
    
    # Replace placeholders in template
    content = template_content.replace("{bucket_name}", bucket_name)
    content = content.replace("{state_key}", state_key)
    content = content.replace("{region}", region)
    content = content.replace("{dynamodb_table}", dynamodb_table)
    
    return content


def inject_files(
    workspace_root: str,
    template_path: str,
    aws_projects: Set[tuple]
) -> None:
    """
    Inject backend.tf files into AWS example projects.
    
    Args:
        workspace_root: Root directory of the workspace
        template_path: Path to backend.tf.template
        aws_projects: Set of AWS project tuples (path, deploy_dir, type)
    """
    # Read template
    with open(template_path, 'r') as f:
        template_content = f.read()
    
    injected_count = 0
    
    for project_path, deploy_dir, project_type in sorted(aws_projects):
        full_project_path = os.path.join(workspace_root, project_path)
        deploy_path = os.path.join(full_project_path, deploy_dir)
        
        if not os.path.exists(deploy_path):
            print(f"⚠️  Warning: Deploy directory not found: {deploy_path}")
            continue
        
        # Generate and write backend.tf
        backend_tf_path = os.path.join(deploy_path, "backend.tf")
        backend_content = generate_backend_tf(template_content, project_path, project_type)
        
        with open(backend_tf_path, 'w') as f:
            f.write(backend_content)
        print(f"✅ Injected backend.tf -> {backend_tf_path}")
        
        injected_count += 1
    
    print(f"\n✨ Successfully injected files into {injected_count} projects")


def main():
    """Main entry point."""
    # Determine workspace root (assuming script is in scripts/deploy)
    script_dir = Path(__file__).parent
    workspace_root = script_dir.parent.parent
    
    # Paths to template
    template_path = script_dir / "backend.tf.template"
    config_path = workspace_root / ".github" / "integration-test-config.yaml"
    
    # Validate required files exist
    if not template_path.exists():
        print(f"❌ Error: Template not found: {template_path}")
        return 1
    
    if not config_path.exists():
        print(f"❌ Error: Config file not found: {config_path}")
        return 1
    
    print("🔍 Loading integration test configuration...")
    config = load_config(str(config_path))
    
    print("🔍 Identifying AWS projects...")
    aws_projects = get_aws_projects(config)
    print(f"   Found {len(aws_projects)} AWS projects")
    
    print("\n📝 Injecting backend files...")
    inject_files(
        str(workspace_root),
        str(template_path),
        aws_projects
    )
    
    return 0


if __name__ == "__main__":
    exit(main())
