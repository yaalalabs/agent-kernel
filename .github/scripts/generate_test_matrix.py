#!/usr/bin/env python3
"""
Generate test matrices for GitHub Actions workflows.
Used by integration tests (nightly/weekly) and e2e test workflows.
"""

import argparse
import yaml
import json
import sys


def generate_matrix_from_config(config_path: str, tier: str) -> tuple[dict, dict]:
    """
    Generate test matrix from configuration file.
    
    Args:
        config_path: Path to configuration file
        tier: Test tier ('nightly', 'weekly', or 'e2e')
    
    Returns:
        Tuple of (matrix dict, deployment_base dict or None)
    """
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    # Get tests based on tier
    if tier in ['nightly', 'weekly']:
        tests = config[tier]['tests']
    elif tier == 'e2e':
        tests = config['e2e']['tests']
    else:
        raise ValueError(f"Invalid tier: {tier}")
    
    matrix_tests = []
    
    for idx, test in enumerate(tests):
        test_item = {
            'id': idx,
            'type': test['type'],
            'path': test['path'],
            'deploy_dir': test.get('deploy_dir', 'deploy')
        }
        
        # Add optional fields
        if 'requires_slack' in test:
            test_item['requires_slack'] = test['requires_slack']
        
        matrix_tests.append(test_item)
    
    # Get deployment base (only for integration tests)
    deployment_base = None
    if tier in ['nightly', 'weekly'] and 'deployment_base' in config and config['deployment_base']:
        base = config['deployment_base'][0]  # Assume single base deployment
        deployment_base = {
            'type': base['type'],
            'path': base['path'],
            'deploy_dir': base.get('deploy_dir', 'deploy')
        }
    
    return {'include': matrix_tests}, deployment_base


def generate_nightly_matrix(config_path: str) -> tuple[dict, dict]:
    """Generate test matrix for nightly workflow."""
    return generate_matrix_from_config(config_path, 'nightly')


def generate_weekly_matrices(config_path: str) -> tuple[dict, dict]:
    """Generate test matrices for weekly workflow."""
    return generate_matrix_from_config(config_path, 'weekly')


def generate_e2e_matrix(config_path: str) -> dict:
    """Generate test matrix for e2e workflow."""
    matrix, _ = generate_matrix_from_config(config_path, 'e2e')
    return matrix


def main():
    parser = argparse.ArgumentParser(description='Generate test matrices for GitHub Actions')
    parser.add_argument(
        '--tier',
        choices=['nightly', 'weekly', 'e2e'],
        required=True,
        help='Test tier to generate matrix for'
    )
    parser.add_argument(
        '--config',
        help='Path to configuration file'
    )
    parser.add_argument(
        '--format',
        choices=['json', 'github'],
        default='github',
        help='Output format (json or github actions format)'
    )
    
    args = parser.parse_args()
    
    # Set default config based on tier
    if not args.config:
        if args.tier == 'e2e':
            args.config = '.github/test-config.yaml'
        else:
            args.config = '.github/integration-test-config.yaml'
    
    try:
        if args.tier == 'e2e':
            matrix = generate_e2e_matrix(args.config)
            if args.format == 'github':
                print(f"matrix={json.dumps(matrix)}")
            else:
                print(json.dumps(matrix, indent=2))
        
        elif args.tier == 'nightly':
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
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
