#!/usr/bin/env python3
"""
Inject dependencies into AWS and Azure example projects.

This script:
1. Injects backend.tf files for Terraform state management
2. Modifies main.tf files to use local module sources instead of registry modules
3. Modifies state.tf files in module directories to use local common modules
4. Can revert all changes back to registry modules

The modifications are intended for local development and CI/CD use.
"""

import os
import re
import yaml
import argparse
from pathlib import Path
from typing import List, Dict, Set, Tuple


MODULE_PATHS = [
    'ak-deployment/ak-aws/serverless',
    'ak-deployment/ak-aws/containerized',
    'ak-deployment/ak-azure/serverless',
    'ak-deployment/ak-azure/containerized'
]


def load_config(config_path: str) -> Dict:
    """Load the integration test configuration YAML file."""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def get_projects(config: Dict) -> Set[tuple]:
    """
    Extract AWS and Azure project paths from the configuration.
    
    Returns a set of tuples: (project_path, deploy_dir, project_type)
    """
    projects = set()
    
    # Include deployment base infrastructure
    if 'deployment_base' in config:
        for project in config['deployment_base']:
            test_type = project.get('type', '')
            if test_type in ['aws-serverless', 'aws-containerized', 'azure-serverless', 'azure-containerized']:
                path = project.get('path', '')
                deploy_dir = project.get('deploy_dir', 'deploy')
                if path:
                    projects.add((path, deploy_dir, test_type))
    
    # Process both nightly and weekly test configs
    for schedule in ['nightly', 'weekly']:
        if schedule in config and 'tests' in config[schedule]:
            for test in config[schedule]['tests']:
                test_type = test.get('type', '')
                if test_type in ['aws-serverless', 'aws-containerized', 'azure-serverless', 'azure-containerized']:
                    path = test.get('path', '')
                    deploy_dir = test.get('deploy_dir', 'deploy')
                    if path:
                        projects.add((path, deploy_dir, test_type))
    
    return projects


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


def calculate_relative_path(from_path: str, project_type: str) -> str:
    """
    Calculate relative path from example deploy directory to module source.
    
    Args:
        from_path: Path to the example (e.g., examples/aws-serverless/adk or examples/azure-serverless/openai)
        project_type: Type of project (aws-serverless, aws-containerized, azure-serverless, or azure-containerized)
    
    Returns:
        Relative path to the module source
    """
    # Determine cloud provider and module type
    if project_type in ['aws-serverless', 'aws-containerized']:
        cloud = 'aws'
        module_subdir = 'serverless' if project_type == 'aws-serverless' else 'containerized'
    elif project_type in ['azure-serverless', 'azure-containerized']:
        cloud = 'azure'
        module_subdir = 'serverless' if project_type == 'azure-serverless' else 'containerized'
    else:
        return None
    
    # Calculate depth from deploy dir (e.g., examples/aws-serverless/adk/deploy)
    # Need to go up to workspace root, then down to module
    depth = len(from_path.split('/')) + 1  # +1 for deploy dir
    up_levels = '../' * depth
    
    return f"{up_levels}ak-deployment/ak-{cloud}/{module_subdir}"


def modify_main_tf(main_tf_path: str, project_path: str, project_type: str) -> bool:
    """
    Modify main.tf to use local module source instead of registry.
    
    Args:
        main_tf_path: Path to main.tf file
        project_path: Path to the project (e.g., examples/aws-serverless/adk or examples/azure-serverless/openai)
        project_type: Type of project (aws-serverless, aws-containerized, azure-serverless, or azure-containerized)
    
    Returns:
        True if modifications were made, False otherwise
    """
    if not os.path.exists(main_tf_path):
        return False
    
    with open(main_tf_path, 'r') as f:
        content = f.read()
    
    original_content = content
    
    # Determine which registry module to replace
    if project_type == 'aws-serverless':
        registry_source = 'yaalalabs/ak-serverless/aws'
    elif project_type == 'aws-containerized':
        registry_source = 'yaalalabs/ak-containerized/aws'
    elif project_type == 'azure-serverless':
        registry_source = 'yaalalabs/ak-serverless/azurerm'
    elif project_type == 'azure-containerized':
        registry_source = 'yaalalabs/ak-containerized/azurerm'
    else:
        return False
    
    # Check if already using local source
    if registry_source not in content:
        return False
    
    # Calculate relative path
    relative_path = calculate_relative_path(project_path, project_type)
    if not relative_path:
        return False
    
    # Replace source line
    # Pattern: source = "yaalalabs/ak-serverless/aws" or source = "yaalalabs/ak-containerized/aws" etc.
    source_pattern = rf'(\s+source\s*=\s*"){re.escape(registry_source)}(")'
    content = re.sub(source_pattern, rf'\1{relative_path}\2', content)
    
    # Comment out version line (should be on next line after source)
    # Pattern: version = "x.x.x"
    version_pattern = r'(\s+)(version\s*=\s*"[^"]*")'
    content = re.sub(version_pattern, r'\1# \2  # Commented for local development', content)
    
    # Only write if changes were made
    if content != original_content:
        with open(main_tf_path, 'w') as f:
            f.write(content)
        return True
    
    return False


def modify_state_tf(state_tf_path: str, module_path: str) -> bool:
    """
    Modify state.tf to use local common modules instead of registry.
    
    Args:
        state_tf_path: Path to state.tf file
        module_path: Path to the module (e.g., ak-deployment/ak-aws/serverless or ak-deployment/ak-azure/serverless)
    
    Returns:
        True if modifications were made, False otherwise
    """
    if not os.path.exists(state_tf_path):
        return False
    
    with open(state_tf_path, 'r') as f:
        content = f.read()
    
    original_content = content
    
    # Determine cloud provider from module path
    is_azure = 'ak-azure' in module_path
    common_registry_pattern = 'yaalalabs/ak-common/azurerm//modules/' if is_azure else 'yaalalabs/ak-common/aws//modules/'
    
    # Check if already using local source
    if common_registry_pattern not in content:
        return False
    
    # Replace all occurrences of registry common modules with local path
    # Pattern: source = "yaalalabs/ak-common/aws//modules/vpc" or source = "yaalalabs/ak-common/azurerm//modules/vpc"
    # Replace with: source = "../common/modules/vpc"
    if is_azure:
        source_pattern = r'(\s+source\s*=\s*)"yaalalabs/ak-common/azurerm//modules/([^"]+)"'
    else:
        source_pattern = r'(\s+source\s*=\s*)"yaalalabs/ak-common/aws//modules/([^"]+)"'
    content = re.sub(source_pattern, r'\1"../common/modules/\2"', content)
    
    # Comment out version lines (for common module references)
    # Pattern: version = "x.x.x" (that comes after a source with ../common)
    # This is trickier, we need to find version lines that follow ../common source lines
    lines = content.split('\n')
    modified_lines = []
    prev_line_has_common_source = False
    
    for line in lines:
        if '../common/modules/' in line and 'source' in line:
            prev_line_has_common_source = True
            modified_lines.append(line)
        elif prev_line_has_common_source and re.match(r'\s+version\s*=\s*"[^"]*"', line):
            # Comment out this version line
            modified_lines.append(re.sub(r'(\s+)(version\s*=\s*"[^"]*")', r'\1# \2  # Commented for local development', line))
            prev_line_has_common_source = False
        else:
            if not re.match(r'\s*$', line):  # Not an empty line
                prev_line_has_common_source = False
            modified_lines.append(line)
    
    content = '\n'.join(modified_lines)
    
    # Only write if changes were made
    if content != original_content:
        with open(state_tf_path, 'w') as f:
            f.write(content)
        return True
    
    return False


def revert_state_tf(state_tf_path: str, module_path: str) -> bool:
    """
    Revert state.tf back to use registry common modules.
    
    Args:
        state_tf_path: Path to state.tf file
        module_path: Path to the module (e.g., ak-deployment/ak-aws/serverless or ak-deployment/ak-azure/serverless)
    
    Returns:
        True if modifications were made, False otherwise
    """
    if not os.path.exists(state_tf_path):
        return False
    
    with open(state_tf_path, 'r') as f:
        content = f.read()
    
    original_content = content
    
    # Check if currently using local source
    if '../common/modules/' not in content:
        return False
    
    # Determine cloud provider from module path
    is_azure = 'ak-azure' in module_path
    common_registry = 'yaalalabs/ak-common/azurerm' if is_azure else 'yaalalabs/ak-common/aws'
    
    # Replace local common modules with registry path
    # Pattern: source = "../common/modules/vpc"
    # Replace with: source = "yaalalabs/ak-common/aws//modules/vpc" or "yaalalabs/ak-common/azurerm//modules/vpc"
    source_pattern = r'(\s+source\s*=\s*)"\.\.\/common\/modules\/([^"]+)"'  
    content = re.sub(source_pattern, rf'\1"{common_registry}//modules/\2"', content)
    
    # Uncomment version lines
    # Pattern: # version = "x.x.x"  # Commented for local development
    version_pattern = r'(\s+)# (version\s*=\s*"[^"]*")\s*# Commented for local development'
    content = re.sub(version_pattern, r'\1\2', content)
    
    # Only write if changes were made
    if content != original_content:
        with open(state_tf_path, 'w') as f:
            f.write(content)
        return True
    
    return False


def revert_main_tf(main_tf_path: str, project_path: str, project_type: str) -> bool:
    """
    Revert main.tf back to use registry module source.
    
    Args:
        main_tf_path: Path to main.tf file
        project_path: Path to the project (e.g., examples/aws-serverless/adk or examples/azure-serverless/openai)
        project_type: Type of project (aws-serverless, aws-containerized, azure-serverless, or azure-containerized)
    
    Returns:
        True if modifications were made, False otherwise
    """
    if not os.path.exists(main_tf_path):
        return False
    
    with open(main_tf_path, 'r') as f:
        content = f.read()
    
    original_content = content
    
    # Determine which registry module to restore
    if project_type == 'aws-serverless':
        registry_source = 'yaalalabs/ak-serverless/aws'
    elif project_type == 'aws-containerized':
        registry_source = 'yaalalabs/ak-containerized/aws'
    elif project_type == 'azure-serverless':
        registry_source = 'yaalalabs/ak-serverless/azurerm'
    elif project_type == 'azure-containerized':
        registry_source = 'yaalalabs/ak-containerized/azurerm'
    else:
        return False
    
    # Calculate relative path to check if it's currently using local source
    relative_path = calculate_relative_path(project_path, project_type)
    if not relative_path:
        return False
    
    escaped_relative_path = re.escape(relative_path)
    
    # Check if currently using local source
    if relative_path not in content:
        return False
    
    # Replace local source with registry source
    # Pattern: source = "../../../../ak-deployment/ak-aws/serverless" or similar
    source_pattern = rf'(\s+source\s*=\s*"){escaped_relative_path}(")'
    content = re.sub(source_pattern, rf'\1{registry_source}\2', content)
    
    # Uncomment version line
    # Pattern: # version = "x.x.x"  # Commented for local development
    version_pattern = r'(\s+)# (version\s*=\s*"[^"]*")\s*# Commented for local development'
    content = re.sub(version_pattern, r'\1\2', content)
    
    # Only write if changes were made
    if content != original_content:
        with open(main_tf_path, 'w') as f:
            f.write(content)
        return True
    
    return False


def revert_dependencies(
    workspace_root: str,
    projects: Set[Tuple[str, str, str]]
) -> None:
    """
    Revert main.tf and state.tf files back to registry modules.
    
    Args:
        workspace_root: Root directory of the workspace
        projects: Set of project tuples (path, deploy_dir, type) for both AWS and Azure
    """
    main_count = 0
    state_count = 0
    
    # Revert example main.tf files
    for project_path, deploy_dir, project_type in sorted(projects):
        full_project_path = os.path.join(workspace_root, project_path)
        deploy_path = os.path.join(full_project_path, deploy_dir)
        
        if not os.path.exists(deploy_path):
            print(f"⚠️  Warning: Deploy directory not found: {deploy_path}")
            continue
        
        # Revert main.tf to use registry modules
        main_tf_path = os.path.join(deploy_path, "main.tf")
        if revert_main_tf(main_tf_path, project_path, project_type):
            print(f"✅ Reverted main.tf -> {main_tf_path}")
            main_count += 1
    
    # Revert module state.tf files
    for module_path in MODULE_PATHS:
        full_module_path = os.path.join(workspace_root, module_path)
        state_tf_path = os.path.join(full_module_path, "state.tf")
        
        if revert_state_tf(state_tf_path, module_path):
            print(f"✅ Reverted state.tf -> {state_tf_path}")
            state_count += 1
    
    print(f"\n✨ Successfully reverted main.tf in {main_count} projects")
    print(f"✨ Successfully reverted state.tf in {state_count} modules")


def inject_dependencies(
    workspace_root: str,
    template_path: str,
    projects: Set[Tuple[str, str, str]]
) -> None:
    """
    Inject backend.tf, modify main.tf in examples, and modify state.tf in modules.
    
    Args:
        workspace_root: Root directory of the workspace
        template_path: Path to backend.tf.template
        projects: Set of project tuples (path, deploy_dir, type) for both AWS and Azure
    """
    # Read template
    with open(template_path, 'r') as f:
        template_content = f.read()
    
    backend_count = 0
    main_count = 0
    state_count = 0
    
    # Process example projects
    for project_path, deploy_dir, project_type in sorted(projects):
        full_project_path = os.path.join(workspace_root, project_path)
        deploy_path = os.path.join(full_project_path, deploy_dir)
        
        if not os.path.exists(deploy_path):
            print(f"⚠️  Warning: Deploy directory not found: {deploy_path}")
            continue
        
        # 1. Generate and write backend.tf
        backend_tf_path = os.path.join(deploy_path, "backend.tf")
        backend_content = generate_backend_tf(template_content, project_path, project_type)
        
        with open(backend_tf_path, 'w') as f:
            f.write(backend_content)
        print(f"✅ Injected backend.tf -> {backend_tf_path}")
        backend_count += 1
        
        # 2. Modify main.tf to use local modules
        main_tf_path = os.path.join(deploy_path, "main.tf")
        if modify_main_tf(main_tf_path, project_path, project_type):
            print(f"✅ Modified main.tf -> {main_tf_path}")
            main_count += 1
    
    # 3. Modify module state.tf files
    for module_path in MODULE_PATHS:
        full_module_path = os.path.join(workspace_root, module_path)
        state_tf_path = os.path.join(full_module_path, "state.tf")
        
        if modify_state_tf(state_tf_path, module_path):
            print(f"✅ Modified state.tf -> {state_tf_path}")
            state_count += 1
    
    print(f"\n✨ Successfully injected backend.tf into {backend_count} projects")
    print(f"✨ Successfully modified main.tf in {main_count} projects")
    print(f"✨ Successfully modified state.tf in {state_count} modules")


def inject_files(
    workspace_root: str,
    template_path: str,
    projects: Set[tuple]
) -> None:
    """
    Inject backend.tf files into AWS and Azure example projects.
    
    Args:
        workspace_root: Root directory of the workspace
        template_path: Path to backend.tf.template
        projects: Set of project tuples (path, deploy_dir, type) for both AWS and Azure
    """
    # Read template
    with open(template_path, 'r') as f:
        template_content = f.read()
    
    injected_count = 0
    
    for project_path, deploy_dir, project_type in sorted(projects):
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
    parser = argparse.ArgumentParser(
        description='Inject or revert dependencies in AWS and Azure example projects'
    )
    parser.add_argument(
        '--revert',
        action='store_true',
        help='Revert main.tf files back to registry modules'
    )
    
    args = parser.parse_args()
    
    # Determine workspace root (assuming script is in scripts/deploy)
    script_dir = Path(__file__).parent
    workspace_root = script_dir.parent.parent
    
    # Paths to template and config
    template_path = script_dir / "backend.tf.template"
    config_path = workspace_root / ".github" / "integration-test-config.yaml"
    
    if not config_path.exists():
        print(f"❌ Error: Config file not found: {config_path}")
        return 1
    
    print("🔍 Loading integration test configuration...")
    config = load_config(str(config_path))
    
    print("🔍 Identifying AWS and Azure projects...")
    projects = get_projects(config)
    print(f"   Found {len(projects)} projects (AWS and Azure)")
    
    if args.revert:
        # Revert mode: restore registry modules
        print("\n🔄 Reverting to registry modules...")
        revert_dependencies(
            str(workspace_root),
            projects
        )
    else:
        # Inject mode: inject backend.tf and modify main.tf
        if not template_path.exists():
            print(f"❌ Error: Template not found: {template_path}")
            return 1
        
        print("\n📝 Injecting dependencies...")
        inject_dependencies(
            str(workspace_root),
            str(template_path),
            projects
        )
    
    return 0


if __name__ == "__main__":
    exit(main())
