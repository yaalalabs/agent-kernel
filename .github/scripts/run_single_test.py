#!/usr/bin/env python3
"""
Run a single test.
Used by parallel GitHub Actions jobs for both integration tests and e2e tests.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def get_base_deployment_outputs(base_path: str = "examples/aws-serverless/openai", deploy_dir: str = "deploy") -> dict:
    """
    Retrieve outputs from the base deployment (aws-serverless/openai).
    Returns a dict with vpc_id and private_subnet_ids.
    """
    deploy_path = Path(base_path) / deploy_dir
    
    if not deploy_path.exists():
        print(f"⚠️  Warning: Base deployment path not found: {deploy_path}")
        return {}
    
    try:
        print(f"\n{'='*80}")
        print(f"Retrieving VPC information from base deployment: {base_path}")
        print(f"{'='*80}\n")
        
        # Get vpc_id
        result = subprocess.run(
            ['terraform', 'output', '-raw', 'vpc_id'],
            cwd=str(deploy_path),
            check=True,
            capture_output=True,
            text=True
        )
        vpc_id = result.stdout.strip()
        
        # Get private_subnet_ids (JSON output)
        result = subprocess.run(
            ['terraform', 'output', '-json', 'private_subnet_ids'],
            cwd=str(deploy_path),
            check=True,
            capture_output=True,
            text=True
        )
        private_subnet_ids = json.loads(result.stdout.strip())
        
        print(f"✅ Retrieved VPC ID: {vpc_id}")
        print(f"✅ Retrieved Private Subnet IDs: {private_subnet_ids}")
        
        return {
            'vpc_id': vpc_id,
            'private_subnet_ids': private_subnet_ids
        }
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Warning: Failed to retrieve VPC information from base deployment: {e}")
        print(f"   This is expected if the base deployment hasn't been deployed yet.")
        return {}
    except json.JSONDecodeError as e:
        print(f"⚠️  Warning: Failed to parse subnet IDs JSON: {e}")
        return {}


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


def destroy_aws_resources(path: str, deploy_dir: str = 'deploy') -> bool:
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
    
    # Get VPC information from base deployment and inject as Terraform variables
    base_outputs = get_base_deployment_outputs()
    if base_outputs:
        vpc_id = base_outputs.get('vpc_id')
        private_subnet_ids = base_outputs.get('private_subnet_ids', [])
        
        if vpc_id and private_subnet_ids:
            # Convert subnet IDs list to Terraform format
            subnet_ids_str = json.dumps(private_subnet_ids)
            
            # Set as Terraform environment variables
            tf_env['TF_VAR_vpc_id'] = vpc_id
            tf_env['TF_VAR_private_subnet_ids'] = subnet_ids_str
            
            print(f"\n✅ Injecting VPC configuration as Terraform variables for destroy:")
            print(f"   TF_VAR_vpc_id={vpc_id}")
            print(f"   TF_VAR_private_subnet_ids={subnet_ids_str}\n")
    
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


def deploy_aws_resources(path: str, deploy_dir: str = 'deploy') -> bool:
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
    
    # Get VPC information from base deployment and inject as Terraform variables
    base_outputs = get_base_deployment_outputs()
    if base_outputs:
        vpc_id = base_outputs.get('vpc_id')
        private_subnet_ids = base_outputs.get('private_subnet_ids', [])
        
        if vpc_id and private_subnet_ids:
            # Convert subnet IDs list to Terraform format
            subnet_ids_str = json.dumps(private_subnet_ids)
            
            # Set as Terraform environment variables
            tf_env['TF_VAR_vpc_id'] = vpc_id
            tf_env['TF_VAR_private_subnet_ids'] = subnet_ids_str
            
            print(f"\n✅ Injecting VPC configuration as Terraform variables:")
            print(f"   TF_VAR_vpc_id={vpc_id}")
            print(f"   TF_VAR_private_subnet_ids={subnet_ids_str}\n")
    
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
                       choices=['api', 'memory', 'cli', 'containerized', 'aws-containerized', 'aws-serverless'])
    parser.add_argument('--path', required=True, help='Path to the test')
    parser.add_argument('--deploy-dir', default='deploy', help='Deploy directory for AWS tests')
    parser.add_argument('--action', choices=['deploy', 'test', 'destroy'], default='test', help='Action to perform')
    
    args = parser.parse_args()
    
    print(f"\n🚀 Running {args.action} for {args.type}: {args.path}\n")
    
    success = False
    
    if args.action == 'deploy':
        if args.type in ['aws-containerized', 'aws-serverless']:
            success = deploy_aws_resources(args.path, args.deploy_dir)
        else:
            print(f"⚠️  Deploy action not applicable for type: {args.type}")
            success = True
    elif args.action == 'destroy':
        if args.type in ['aws-containerized', 'aws-serverless']:
            success = destroy_aws_resources(args.path, args.deploy_dir)
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
    
    if success:
        print(f"\n✅ SUCCESS: {args.path}")
        sys.exit(0)
    else:
        print(f"\n❌ FAILED: {args.path}")
        sys.exit(1)


if __name__ == '__main__':
    main()
