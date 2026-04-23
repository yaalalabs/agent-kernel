#!/usr/bin/env python3
"""
Run a single test.
Used by parallel GitHub Actions jobs for both integration tests and e2e tests.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def run_command(command: list[str], cwd: str = None, description: str = "", env: dict = None) -> bool:
    """Run a shell command and return success status."""
    try:
        print(f"\n{'='*80}")
        print(f"Running: {description}")
        print(f"Command: {' '.join(command)}")
        print(f"Directory: {cwd or 'current'}")
        print(f"{'='*80}\n")
        
        # Merge environment variables
        cmd_env = os.environ.copy()
        if env:
            cmd_env.update(env)
        
        subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=False,
            text=True,
            env=cmd_env
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Failed: {description}")
        print(f"Error: {e}")
        return False


def run_simple_test(path: str) -> bool:
    """
    Run a simple test (cli, api, memory, containerized).
    These tests follow the same pattern: build.sh local, then pytest.
    """
    build_script = Path(path) / 'build.sh'
    
    if not build_script.exists():
        print(f"⚠️  Skipping {path} - no build.sh found")
        return True
    
    # Build
    if not run_command(
        ['./build.sh', 'local'],
        cwd=path,
        description=f"Building {path}"
    ):
        return False
    
    # Test
    return run_command(
        ['uv', 'run', 'pytest', '-s', '--junitxml=pytest-report.xml'],
        cwd=path,
        description=f"Testing {path}"
    )


def run_api_test(path: str) -> bool:
    """Run API example test."""
    return run_simple_test(path)


def run_memory_test(path: str) -> bool:
    """Run Memory example test."""
    return run_simple_test(path)


def run_cli_test(path: str) -> bool:
    """Run CLI example test."""
    return run_simple_test(path)


def run_containerized_test(path: str) -> bool:
    """Run containerized example test."""
    return run_simple_test(path)

def destroy_azure_resources(path: str, deploy_dir: str = 'deploy', vnet_id: str = None, subnet_ids: str = None) -> bool:
    """Destroy Azure resources."""
    deploy_path = Path(path) / deploy_dir
    deploy_script = deploy_path / 'deploy.sh'
    
    if not deploy_path.exists():
        print(f"⚠️  Skipping {path} - deploy directory not found: {deploy_path}")
        return True
    
    if not deploy_script.exists():
        print(f"⚠️  Skipping {path} - no deploy.sh found at {deploy_path}")
        return True
    
    # Set environment variables for non-interactive CI execution
    env = {}
    
    # Inject VNet configuration as environment variables if provided
    if vnet_id and subnet_ids:
        env['TF_VAR_vnet_id'] = vnet_id
        env['TF_VAR_subnet_ids'] = subnet_ids
        
        print(f"\n✅ Injecting VNet configuration as environment variables for destroy:")
        print(f"   TF_VAR_VNET_ID={vnet_id}")
        print(f"   TF_VAR_SUBNET_IDS={subnet_ids}\n")
    
    # Destroy
    return run_command(
        ['./deploy.sh', 'destroy'],
        cwd=str(deploy_path),
        description=f"Destroying {path}",
        env=env
    )

def deploy_azure_resources(path: str, deploy_dir: str = 'deploy', vnet_id: str = None, subnet_ids: str = None) -> bool:
    """Deploy Azure resources only (without running tests)."""
    deploy_path = Path(path) / deploy_dir
    deploy_script = deploy_path / 'deploy.sh'
    
    if not deploy_path.exists():
        print(f"⚠️  Skipping {path} - deploy directory not found: {deploy_path}")
        return True
    
    if not deploy_script.exists():
        print(f"⚠️  Skipping {path} - no deploy.sh found at {deploy_path}")
        return True
    
    # Set environment variables for non-interactive CI execution
    tf_env = {
        'TF_INPUT': '0',  # Disable interactive prompts
        'TF_CLI_ARGS_apply': '-auto-approve',  # Auto-approve applies
    }
    
    
    # Inject VNet configuration as environment variables if provided
    if vnet_id and subnet_ids:
        env['TF_VAR_vnet_id'] = vnet_id
        env['TF_VAR_subnet_ids'] = subnet_ids
        
        print(f"\n✅ Injecting VNet configuration as environment variables:")
        print(f"   TF_VAR_vnet_id={vnet_id}")
        print(f"   TF_VAR_subnet_ids={subnet_ids}\n")
    
    # Initialize terraform if needed
    if not run_command(
        ['terraform', 'init', '-upgrade'],
        cwd=str(deploy_path),
        description=f"Terraform init for {path}",
        env=env
    ):
        return False

    # Deploy
    return run_command(
        ['./deploy.sh', 'local'],
        cwd=str(deploy_path),
        description=f"Deploying {path}",
        env=env
    )   

def test_azure_deployment(path: str, deploy_dir: str = 'deploy') -> bool:
    """Test an already deployed Azure resource."""
    deploy_path = Path(path) / deploy_dir
    
    if not deploy_path.exists():
        print(f"⚠️  Skipping {path} - deploy directory not found: {deploy_path}")
        return True
    
    # Get agent_invoke_url terraform output and set AK_TEST_ENDPOINT
    try:
        print(f"\n{'='*80}")
        print(f"Retrieving agent_invoke_url terraform output")
        print(f"{'='*80}\n")
        
        result = subprocess.run(
            ['terraform', 'output', '-raw', 'agent_invoke_url'],
            cwd=str(deploy_path),
            check=True,
            capture_output=True,
            text=True
        )
        agent_invoke_url = result.stdout.strip()
        if not agent_invoke_url:
            print("❌ Failed to retrieve agent_invoke_url: output was empty.")
            return False
        print(f"✅ agent_invoke_url: {agent_invoke_url}")
        
        # Set as environment variable for test
        test_env = {'AK_TEST_ENDPOINT': agent_invoke_url}
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to retrieve agent_invoke_url output: {e}")
        return False
    
    #remove the config.yaml till the issue with it is being solved
    
    delete_config = run_command(
        ['rm', '-f', 'config.yaml'],
        cwd=path,
        description=f"Removing config.yaml for {path}"
    )
    
    # Test
    return run_command(
        ['uv', 'run', 'pytest', '-s', '--junitxml=pytest-report.xml'],
        cwd=path,
        description=f"Testing {path}",
        env=test_env
    )

def destroy_aws_resources(path: str, deploy_dir: str = 'deploy', vpc_id: str = None, private_subnet_ids: str = None) -> bool:
    """Destroy AWS resources."""
    deploy_path = Path(path) / deploy_dir
    deploy_script = deploy_path / 'deploy.sh'
    
    if not deploy_path.exists():
        print(f"⚠️  Skipping {path} - deploy directory not found: {deploy_path}")
        return True
    
    if not deploy_script.exists():
        print(f"⚠️  Skipping {path} - no deploy.sh found at {deploy_path}")
        return True
    
    # Set Terraform automation flags for non-interactive CI execution
    tf_env = {
        'TF_INPUT': '0',  # Disable interactive prompts
    }
    
    # Inject VPC configuration as Terraform variables if provided
    if vpc_id and private_subnet_ids:
        tf_env['TF_VAR_vpc_id'] = vpc_id
        tf_env['TF_VAR_private_subnet_ids'] = private_subnet_ids
        
        print(f"\n✅ Injecting VPC configuration as Terraform variables for destroy:")
        print(f"   TF_VAR_vpc_id={vpc_id}")
        print(f"   TF_VAR_private_subnet_ids={private_subnet_ids}\n")
    
    # Initialize terraform if needed
    if not run_command(
        ['terraform', 'init', '-upgrade'],
        cwd=str(deploy_path),
        description=f"Terraform init for {path}",
        env=tf_env
    ):
        return False
    
    # Destroy (already has -auto-approve flag)
    return run_command(
        ['terraform', 'destroy', '-auto-approve'],
        cwd=str(deploy_path),
        description=f"Destroying {path}",
        env=tf_env
    )


def deploy_aws_resources(path: str, deploy_dir: str = 'deploy', vpc_id: str = None, private_subnet_ids: str = None) -> bool:
    """Deploy AWS resources only (without running tests)."""
    deploy_path = Path(path) / deploy_dir
    deploy_script = deploy_path / 'deploy.sh'
    
    if not deploy_path.exists():
        print(f"⚠️  Skipping {path} - deploy directory not found: {deploy_path}")
        return True
    
    if not deploy_script.exists():
        print(f"⚠️  Skipping {path} - no deploy.sh found at {deploy_path}")
        return True
    
    # Set Terraform automation flags for non-interactive CI execution
    tf_env = {
        'TF_INPUT': '0',  # Disable interactive prompts
        'TF_CLI_ARGS_apply': '-auto-approve',  # Auto-approve applies
    }
    
    # Inject VPC configuration as Terraform variables if provided
    if vpc_id and private_subnet_ids:
        tf_env['TF_VAR_vpc_id'] = vpc_id
        tf_env['TF_VAR_private_subnet_ids'] = private_subnet_ids
        
        print(f"\n✅ Injecting VPC configuration as Terraform variables:")
        print(f"   TF_VAR_vpc_id={vpc_id}")
        print(f"   TF_VAR_private_subnet_ids={private_subnet_ids}\n")
    
    # Initialize terraform if needed
    if not run_command(
        ['terraform', 'init', '-upgrade'],
        cwd=str(deploy_path),
        description=f"Terraform init for {path}",
        env=tf_env
    ):
        return False
    
    # Deploy
    return run_command(
        ['./deploy.sh', 'local'],
        cwd=str(deploy_path),
        description=f"Deploying {path}",
        env=tf_env
    )


def test_aws_deployment(path: str, deploy_dir: str = 'deploy') -> bool:
    """Test an already deployed AWS resource."""
    deploy_path = Path(path) / deploy_dir
    
    if not deploy_path.exists():
        print(f"⚠️  Skipping {path} - deploy directory not found: {deploy_path}")
        return True
    
    # Get agent_invoke_url terraform output and set AK_TEST_ENDPOINT
    try:
        print(f"\n{'='*80}")
        print(f"Retrieving agent_invoke_url terraform output")
        print(f"{'='*80}\n")
        
        result = subprocess.run(
            ['terraform', 'output', '-raw', 'agent_invoke_url'],
            cwd=str(deploy_path),
            check=True,
            capture_output=True,
            text=True
        )
        agent_invoke_url = result.stdout.strip()
        if not agent_invoke_url:
            print("❌ Failed to retrieve agent_invoke_url: output was empty.")
            return False
        print(f"✅ agent_invoke_url: {agent_invoke_url}")
        
        # Set as environment variable for test
        test_env = {'AK_TEST_ENDPOINT': agent_invoke_url}
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to retrieve agent_invoke_url output: {e}")
        return False
    
    # Test
    return run_command(
        ['uv', 'run', 'pytest', '-s', '--junitxml=pytest-report.xml'],
        cwd=path,
        description=f"Testing {path}",
        env=test_env
    )


def main():
    parser = argparse.ArgumentParser(description='Run a single test')
    parser.add_argument('--type', required=True, 
                       choices=['api', 'memory', 'cli', 'containerized', 'aws-containerized', 'aws-serverless', 'azure-containerized', 'azure-serverless'])
    parser.add_argument('--path', required=True, help='Path to the test')
    parser.add_argument('--deploy-dir', default='deploy', help='Deploy directory for AWS tests')
    parser.add_argument('--action', choices=['deploy', 'test', 'destroy'], default='test', help='Action to perform')
    parser.add_argument('--vpc-id', default=None, help='VPC ID from base deployment')
    parser.add_argument('--private-subnet-ids', default=None, help='Private subnet IDs (JSON array) from base deployment')
    
    args = parser.parse_args()
    
    print(f"\n🚀 Running {args.action} for {args.type}: {args.path}\n")
    
    success = False
    
    if args.action == 'deploy':
        if args.type in ['aws-containerized', 'aws-serverless']:
            success = deploy_aws_resources(args.path, args.deploy_dir, args.vpc_id, args.private_subnet_ids)
        elif args.type in ['azure-serverless', 'azure-containerized']:
            success = deploy_azure_resources(args.path, args.deploy_dir, args.vpc_id, args.private_subnet_ids)
        else:
            print(f"⚠️  Deploy action not applicable for type: {args.type}")
            success = True
    elif args.action == 'destroy':
        if args.type in ['aws-containerized', 'aws-serverless']:
            success = destroy_aws_resources(args.path, args.deploy_dir, args.vpc_id, args.private_subnet_ids)
        elif args.type in ['azure-serverless', 'azure-containerized']:
            success = destroy_azure_resources(args.path, args.deploy_dir, args.vpc_id, args.private_subnet_ids)
        else:
            print(f"⚠️  Destroy action not applicable for type: {args.type}")
            success = True
    else:  # test action
        if args.type == 'api':
            success = run_api_test(args.path)
        elif args.type == 'memory':
            success = run_memory_test(args.path)
        elif args.type == 'cli':
            success = run_cli_test(args.path)
        elif args.type == 'containerized':
            success = run_containerized_test(args.path)
        elif args.type in ['aws-containerized', 'aws-serverless']:
            success = test_aws_deployment(args.path, args.deploy_dir)
        elif args.type in ['azure-containerized', 'azure-serverless']:
            success = test_azure_deployment(args.path, args.deploy_dir)
        else:
            print(f"  Test action not applicable for type: {args.type}")
            success = False
    
    if success:
        print(f"\n✅ SUCCESS: {args.path}")
        sys.exit(0)
    else:
        print(f"\n❌ FAILED: {args.path}")
        sys.exit(1)


if __name__ == '__main__':
    main()
