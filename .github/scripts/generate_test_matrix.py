#!/usr/bin/env python3
"""
Generate test matrices for GitHub Actions workflows.
Used by both nightly and weekly integration test workflows.
"""

import argparse
import yaml
import json
import sys


def generate_nightly_matrix(config_path: str) -> dict:
    """
    Generate test matrix for nightly workflow.
    Excludes aws-serverless/openai as it runs first separately.
    """
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    tests = config['nightly']['tests']
    matrix_tests = []
    
    for idx, test in enumerate(tests):
        # Skip aws-serverless/openai as it runs first separately
        if test['path'] == 'examples/aws-serverless/openai':
            continue
        matrix_tests.append({
            'id': idx,
            'type': test['type'],
            'path': test['path'],
            'deploy_dir': test.get('deploy_dir', 'deploy')
        })
    
    return {'include': matrix_tests}


def generate_weekly_matrices(config_path: str) -> tuple[dict, list]:
    """
    Generate test matrices for weekly workflow.
    Returns both the full test matrix and AWS-only tests for destruction phase.
    """
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    tests = config['weekly']['tests']
    matrix_tests = []
    aws_tests = []
    
    for idx, test in enumerate(tests):
        matrix_tests.append({
            'id': idx,
            'type': test['type'],
            'path': test['path'],
            'deploy_dir': test.get('deploy_dir', 'deploy')
        })
        
        # Collect AWS tests for destruction phase
        if test['type'] in ['aws-containerized', 'aws-serverless']:
            aws_tests.append({
                'type': test['type'],
                'path': test['path'],
                'deploy_dir': test.get('deploy_dir', 'deploy')
            })
    
    return {'include': matrix_tests}, aws_tests


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
            matrix = generate_nightly_matrix(args.config)
            if args.format == 'github':
                print(f"matrix={json.dumps(matrix)}")
            else:
                print(json.dumps(matrix, indent=2))
        
        elif args.tier == 'weekly':
            matrix, aws_tests = generate_weekly_matrices(args.config)
            if args.format == 'github':
                print(f"matrix={json.dumps(matrix)}")
                print(f"aws-tests={json.dumps(aws_tests)}")
            else:
                print("Test Matrix:")
                print(json.dumps(matrix, indent=2))
                print("\nAWS Tests:")
                print(json.dumps(aws_tests, indent=2))
    
    except Exception as e:
        print(f"Error generating matrices: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
