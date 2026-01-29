#!/usr/bin/env python3
"""
Validate integration test configuration file.
Checks for:
- Valid YAML syntax
- Required fields
- Valid paths
- No duplicate tests
"""

import yaml
import sys
from pathlib import Path
from typing import Set


def validate_config(config_path: str = '.github/integration-test-config.yaml'):
    """Validate the integration test configuration."""
    config_file = Path(config_path)
    
    if not config_file.exists():
        print(f"❌ Configuration file not found: {config_path}")
        return False
    
    try:
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"❌ Invalid YAML syntax: {e}")
        return False
    
    print("✅ Valid YAML syntax")
    
    # Check required tiers
    required_tiers = ['nightly', 'weekly']
    for tier in required_tiers:
        if tier not in config:
            print(f"❌ Missing required tier: {tier}")
            return False
    
    print("✅ All required tiers present (nightly, weekly)")
    
    # Validate each tier
    all_valid = True
    for tier in required_tiers:
        print(f"\n🔍 Validating {tier} tier...")
        tier_valid = True  # Track validity for this tier only
        
        if 'tests' not in config[tier]:
            print(f"  ❌ Missing 'tests' key in {tier}")
            tier_valid = False
            all_valid = False
            continue
        
        tests = config[tier]['tests']
        if not isinstance(tests, list):
            print(f"  ❌ 'tests' must be a list in {tier}")
            tier_valid = False
            all_valid = False
            continue
        
        print(f"  ℹ️  Total tests: {len(tests)}")
        
        seen_paths: Set[str] = set()
        valid_types = {'api', 'memory', 'aws-containerized', 'aws-serverless'}
        
        for idx, test in enumerate(tests, 1):
            if not isinstance(test, dict):
                print(f"  ❌ Test {idx} is not a dictionary")
                tier_valid = False
                continue
            
            # Check required fields
            if 'type' not in test:
                print(f"  ❌ Test {idx} missing 'type' field")
                tier_valid = False
                continue
            
            if 'path' not in test:
                print(f"  ❌ Test {idx} missing 'path' field")
                tier_valid = False
                continue
            
            test_type = test['type']
            test_path = test['path']
            
            # Validate type
            if test_type not in valid_types:
                print(f"  ❌ Test {idx} has invalid type: {test_type}")
                print(f"     Valid types: {', '.join(valid_types)}")
                tier_valid = False
            
            # Check for duplicates
            if test_path in seen_paths:
                print(f"  ⚠️  Test {idx} is duplicate: {test_path}")
            seen_paths.add(test_path)
            
            # Validate path exists
            if not Path(test_path).exists():
                print(f"  ⚠️  Test {idx} path does not exist: {test_path}")
            
            # For AWS tests, check deploy_dir
            if test_type in ['aws-containerized', 'aws-serverless']:
                deploy_dir = test.get('deploy_dir', 'deploy')
                full_deploy_path = Path(test_path) / deploy_dir
                
                if not full_deploy_path.exists():
                    print(f"  ⚠️  Test {idx} deploy directory not found: {full_deploy_path}")
                
                deploy_script = full_deploy_path / 'deploy.sh'
                if not deploy_script.exists():
                    print(f"  ⚠️  Test {idx} deploy.sh not found: {deploy_script}")
        
        # Update global validity and print tier-specific message
        all_valid = all_valid and tier_valid
        if tier_valid:
            print(f"  ✅ {tier} tier configuration valid")
    
    if all_valid:
        print("\n✅ Configuration file is valid!")
    else:
        print("\n❌ Configuration file has errors")
    
    return all_valid


if __name__ == '__main__':
    config_path = sys.argv[1] if len(sys.argv) > 1 else '.github/integration-test-config.yaml'
    success = validate_config(config_path)
    sys.exit(0 if success else 1)
