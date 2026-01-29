#!/usr/bin/env python3
"""
Generate test matrices for GitHub Actions workflows.
Used by both nightly and weekly integration test workflows.
"""

import argparse
import yaml
import json
import sys


def generate_nightly_matrix(config_path: str) -> tuple[dict, dict]:
    """
    Generate test matrix for nightly workflow.
    Returns the test matrix and deployment_base info.
    """
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    tests = config['nightly']['tests']
    matrix_tests = []
    
    for idx, test in enumerate(tests):
        matrix_tests.append({
            'id': idx,
            'type': test['type'],
            'path': test['path'],
            'deploy_dir': test.get('deploy_dir', 'deploy')
        })
    
    # Get deployment base (supporting infrastructure)
    deployment_base = None
    if 'deployment_base' in config and config['deployment_base']:
        base = config['deployment_base'][0]  # Assume single base deployment
        deployment_base = {
            'type': base['type'],
            'path': base['path'],
            'deploy_dir': base.get('deploy_dir', 'deploy')
        }
    
    return {'include': matrix_tests}, deployment_base


def generate_weekly_matrices(config_path: str) -> tuple[dict, dict]:
    """
    Generate test matrices for weekly workflow.
    Returns the test matrix and deployment_base info.
    """
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    tests = config['weekly']['tests']
    matrix_tests = []
    
    for idx, test in enumerate(tests):
        matrix_tests.append({
            'id': idx,
            'type': test['type'],
            'path': test['path'],
            'deploy_dir': test.get('deploy_dir', 'deploy')
        })
    
    # Get deployment base (supporting infrastructure)
    deployment_base = None
    if 'deployment_base' in config and config['deployment_base']:
        base = config['deployment_base'][0]  # Assume single base deployment
        deployment_base = {
            'type': base['type'],
            'path': base['path'],
            'deploy_dir': base.get('deploy_dir', 'deploy')
        }
    
    return {'include': matrix_tests}, deployment_base


def main():
    parser = argparse.ArgumentParser(description='Generate test matrices for GitHub Actions')
    parser.add_argument(
        '--tier',
        choices=['nightly', 'weekly'],
        required=True,
        help='Test tier to generate matrix for'
    )
    parser.add_argument(
        '--config',
        default='.github/integration-test-config.yaml',
        help='Path to configuration file'
    )
    parser.add_argument(
        '--format',
        choices=['json', 'github'],
        default='github',
        help='Output format (json or github actions format)'
    )
    
    args = parser.parse_args()
    
    try:
        if args.tier == 'nightly':
            matrix, deployment_base = generate_nightly_matrix(args.config)
            if args.format == 'github':
                print(f"matrix={json.dumps(matrix)}")
                if deployment_base:
                    print(f"deployment-base={json.dumps(deployment_base)}")
            else:
                print(json.dumps(matrix, indent=2))
                if deployment_base:
                    print("\nDeployment Base:")
                    print(json.dumps(deployment_base, indent=2))
        
        elif args.tier == 'weekly':
            matrix, deployment_base = generate_weekly_matrices(args.config)
            if args.format == 'github':
                print(f"matrix={json.dumps(matrix)}")
                if deployment_base:
                    print(f"deployment-base={json.dumps(deployment_base)}")
            else:
                print("Test Matrix:")
                print(json.dumps(matrix, indent=2))
                if deployment_base:
                    print("\nDeployment Base:")
                    print(json.dumps(deployment_base, indent=2))
    
    except Exception as e:
        print(f"Error generating matrices: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
