#!/usr/bin/env python3
"""Tests for update_terraform_versions.py script."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from update_terraform_versions import update_terraform_versions


def test_update_basic_module():
    """Test updating a basic module version."""
    content = '''
module "vpc" {
  source = "yaalalabs/ak-common/aws//modules/vpc"
  version = "0.1.0"
  
  vpc_cidr = "10.0.0.0/16"
}
'''
    expected = '''
module "vpc" {
  source = "yaalalabs/ak-common/aws//modules/vpc"
  version = "0.2.0"
  
  vpc_cidr = "10.0.0.0/16"
}
'''
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.tf', delete=False) as f:
        f.write(content)
        f.flush()
        temp_path = Path(f.name)
    
    try:
        was_modified, num_updates = update_terraform_versions(temp_path, "0.2.0")
        
        assert was_modified, "File should be modified"
        assert num_updates == 1, f"Expected 1 update, got {num_updates}"
        
        with open(temp_path, 'r') as f:
            result = f.read()
        
        assert result == expected, f"Content mismatch:\n{result}"
        print("✅ test_update_basic_module passed")
    finally:
        temp_path.unlink()


def test_update_multiple_modules():
    """Test updating multiple modules in one file."""
    content = '''
module "vpc" {
  source = "yaalalabs/ak-common/aws//modules/vpc"
  version = "0.1.0"
  vpc_cidr = "10.0.0.0/16"
}

module "redis" {
  source = "yaalalabs/ak-common/aws//modules/redis"
  version = "0.1.0"
  env_alias = "prod"
}
'''
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.tf', delete=False) as f:
        f.write(content)
        f.flush()
        temp_path = Path(f.name)
    
    try:
        was_modified, num_updates = update_terraform_versions(temp_path, "0.2.0-beta1")
        
        assert was_modified, "File should be modified"
        assert num_updates == 2, f"Expected 2 updates, got {num_updates}"
        
        with open(temp_path, 'r') as f:
            result = f.read()
        
        assert 'version = "0.2.0-beta1"' in result
        assert result.count('version = "0.2.0-beta1"') == 2
        print("✅ test_update_multiple_modules passed")
    finally:
        temp_path.unlink()


def test_update_app_terraform_io():
    """Test updating modules with app.terraform.io prefix."""
    content = '''
module "serverless" {
  source = "app.terraform.io/yaalalabs/ak-serverless/aws"
  version = "0.1.0"
  function_name = "my-function"
}
'''
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.tf', delete=False) as f:
        f.write(content)
        f.flush()
        temp_path = Path(f.name)
    
    try:
        was_modified, num_updates = update_terraform_versions(temp_path, "0.2.0")
        
        assert was_modified, "File should be modified"
        assert num_updates == 1, f"Expected 1 update, got {num_updates}"
        
        with open(temp_path, 'r') as f:
            result = f.read()
        
        assert 'version = "0.2.0"' in result
        print("✅ test_update_app_terraform_io passed")
    finally:
        temp_path.unlink()


def test_skip_non_yaalalabs_modules():
    """Test that non-yaalalabs modules are not updated."""
    content = '''
module "lambda" {
  source = "terraform-aws-modules/lambda/aws"
  version = "8.0.1"
  function_name = "my-function"
}

module "vpc" {
  source = "yaalalabs/ak-common/aws//modules/vpc"
  version = "0.1.0"
  vpc_cidr = "10.0.0.0/16"
}
'''
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.tf', delete=False) as f:
        f.write(content)
        f.flush()
        temp_path = Path(f.name)
    
    try:
        was_modified, num_updates = update_terraform_versions(temp_path, "0.2.0")
        
        assert was_modified, "File should be modified"
        assert num_updates == 1, f"Expected 1 update, got {num_updates}"
        
        with open(temp_path, 'r') as f:
            result = f.read()
        
        # Non-yaalalabs module should keep old version
        assert 'terraform-aws-modules/lambda/aws"\n  version = "8.0.1"' in result
        # yaalalabs module should be updated
        assert 'yaalalabs/ak-common/aws//modules/vpc"\n  version = "0.2.0"' in result
        print("✅ test_skip_non_yaalalabs_modules passed")
    finally:
        temp_path.unlink()


def test_no_changes_when_no_modules():
    """Test that files without yaalalabs modules are not modified."""
    content = '''
resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"
}
'''
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.tf', delete=False) as f:
        f.write(content)
        f.flush()
        temp_path = Path(f.name)
    
    try:
        was_modified, num_updates = update_terraform_versions(temp_path, "0.2.0")
        
        assert not was_modified, "File should not be modified"
        assert num_updates == 0, f"Expected 0 updates, got {num_updates}"
        print("✅ test_no_changes_when_no_modules passed")
    finally:
        temp_path.unlink()


if __name__ == "__main__":
    print("Running tests for update_terraform_versions.py...\n")
    
    test_update_basic_module()
    test_update_multiple_modules()
    test_update_app_terraform_io()
    test_skip_non_yaalalabs_modules()
    test_no_changes_when_no_modules()
    
    print("\n✅ All tests passed!")
