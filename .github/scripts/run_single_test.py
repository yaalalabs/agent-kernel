#!/usr/bin/env python3
"""
Run a single integration test.
Used by parallel GitHub Actions jobs.
"""

import argparse
import subprocess
import sys
from pathlib import Path


def run_command(command: list[str], cwd: str = None, description: str = "") -> bool:
    """Run a shell command and return success status."""
    try:
        print(f"\n{'='*80}")
        print(f"Running: {description}")
        print(f"Command: {' '.join(command)}")
        print(f"Directory: {cwd or 'current'}")
        print(f"{'='*80}\n")
        
        subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=False,
            text=True
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Failed: {description}")
        print(f"Error: {e}")
        return False


def run_api_test(path: str) -> bool:
    """Run API example test."""
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


def run_memory_test(path: str) -> bool:
    """Run Memory example test."""
    build_script = Path(path) / 'build.sh'
    test_file = Path(path) / 'app_test.py'
    
    if not build_script.exists():
        print(f"⚠️  Skipping {path} - no build.sh found")
        return True
    
    if not test_file.exists():
        print(f"⚠️  Skipping {path} - no app_test.py found")
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


def run_aws_test(path: str, deploy_dir: str = 'deploy') -> bool:
    """Run AWS example test (deploy and test)."""
    deploy_path = Path(path) / deploy_dir
    deploy_script = deploy_path / 'deploy.sh'
    
    if not deploy_path.exists():
        print(f"⚠️  Skipping {path} - deploy directory not found: {deploy_path}")
        return True
    
    if not deploy_script.exists():
        print(f"⚠️  Skipping {path} - no deploy.sh found at {deploy_path}")
        return True
    
    # Deploy
    if not run_command(
        ['./deploy.sh', 'local'],
        cwd=str(deploy_path),
        description=f"Deploying {path}"
    ):
        return False
    
    # Test
    return run_command(
        ['uv', 'run', 'pytest', '-s', '--junitxml=pytest-report.xml'],
        cwd=path,
        description=f"Testing {path}"
    )


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
    
    # Initialize terraform if needed
    if not run_command(
        ['terraform', 'init', '-upgrade'],
        cwd=str(deploy_path),
        description=f"Terraform init for {path}"
    ):
        return False
    
    # Destroy
    return run_command(
        ['terraform', 'destroy', '-auto-approve'],
        cwd=str(deploy_path),
        description=f"Destroying {path}"
    )


def main():
    parser = argparse.ArgumentParser(description='Run a single integration test')
    parser.add_argument('--type', required=True, choices=['api', 'memory', 'aws-containerized', 'aws-serverless'])
    parser.add_argument('--path', required=True, help='Path to the test')
    parser.add_argument('--deploy-dir', default='deploy', help='Deploy directory for AWS tests')
    parser.add_argument('--action', choices=['test', 'destroy'], default='test', help='Action to perform')
    
    args = parser.parse_args()
    
    print(f"\n🚀 Running {args.action} for {args.type}: {args.path}\n")
    
    success = False
    
    if args.action == 'destroy':
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
        elif args.type in ['aws-containerized', 'aws-serverless']:
            success = run_aws_test(args.path, args.deploy_dir)
    
    if success:
        print(f"\n✅ SUCCESS: {args.path}")
        sys.exit(0)
    else:
        print(f"\n❌ FAILED: {args.path}")
        sys.exit(1)


if __name__ == '__main__':
    main()
