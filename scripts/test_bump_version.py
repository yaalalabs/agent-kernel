#!/usr/bin/env python3
"""
Unit tests for bump_version.py

This test file can be run directly with: python test_bump_version.py
It can also be imported and run as part of a test suite.
"""

import sys
from pathlib import Path

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from bump_version import bump_version


# Test cases: (current_version, bump_type, prerelease_type, auto_increment, expected_version)
TEST_CASES = [
    ("0.1.0a1", "patch", "alpha", True, "0.1.0a2"),  # Patch bump with alpha
    ("0.1.1a1", "patch", "alpha", True, "0.1.1a2"),  # Another patch with alpha
    ("0.1.1a1", "minor", "alpha", True, "0.2.0a1"),  # Minor bump with alpha
    ("0.2.0a1", "minor", "alpha", True, "0.2.0a2"),  # Minor bump with already existing alpha
    ("0.2.0a1", "major", "alpha", True, "1.0.0a1"),  # Major bump with already existing alpha
    ("0.1.0", "patch", "alpha", True, "0.1.1a1"),  # First alpha from stable
    ("0.1.0a1", "patch", "", True, "0.1.0"),  # Stable patch release from alpha
    ("0.2.0b2", "patch", "", True, "0.2.0"),  # Stable patch release from beta
    ("2.0.0b6", "major", "", True, "2.0.0"),  # Stable major release from beta
    ("2.4.0b7", "minor", "", True, "2.4.0"),  # Stable minor release from beta
    ("4.5.6", "major", "", True, "5.0.0"),  # Stable major release from stable
    ("4.5.6", "minor", "", True, "4.6.0"),  # Stable minor release from stable
    ("4.5.6", "patch", "", True, "4.5.7"),  # Stable patch release from stable
    ("0.1.0", "minor", "beta", True, "0.2.0b1"),  # Minor bump with beta
    ("0.1.0", "major", "", True, "1.0.0"),  # Major bump stable
    ("1.0.0", "major", "beta", True, "2.0.0b1"),  # Major bump beta
    ("2.0.0b1", "major", "beta", True, "2.0.0b2"),  # Another major bump beta
    ("3.2.0b1", "minor", "beta", True, "3.2.0b2"),  # Another minor bump beta
    ("0.2.0b1", "minor", "beta", True, "0.2.0b2"),  # Another minor with beta
    ("0.2.0a7", "patch", "beta", True, "0.2.0b1"),  # Alpha to beta patch
    ("0.2.4a6", "minor", "beta", True, "0.3.0b1"),  # Alpha to beta minor
    ("0.3.0a6", "minor", "beta", True, "0.3.0b1"),  # Alpha to beta minor
    ("0.3.5a6", "major", "beta", True, "1.0.0b1"),  # Alpha to beta major
    ("1.0.0a6", "major", "beta", True, "1.0.0b1"),  # Alpha to beta major
]


def run_tests():
    """Run all test cases and report results."""
    passed = 0
    failed = 0
    errors = []
    
    print(f"Running {len(TEST_CASES)} test cases...")
    print()
    
    for i, (current, bump, pre, auto, expected) in enumerate(TEST_CASES, 1):
        pre_arg = pre if pre else None
        
        try:
            result = bump_version(current, bump, pre_arg, auto_increment_prerelease=auto)
            
            if result == expected:
                passed += 1
                print(f"✓ Test {i:2d}: {current:10s} + {bump:5s} ({pre or 'stable':6s}) = {result:10s}")
            else:
                failed += 1
                error_msg = f"✗ Test {i:2d}: {current:10s} + {bump:5s} ({pre or 'stable':6s}) = {result:10s} (expected {expected})"
                print(error_msg)
                errors.append(error_msg)
        except Exception as e:
            failed += 1
            error_msg = f"✗ Test {i:2d}: {current:10s} + {bump:5s} ({pre or 'stable':6s}) - ERROR: {e}"
            print(error_msg)
            errors.append(error_msg)
    
    print()
    print("=" * 80)
    print(f"Test Results: {passed} passed, {failed} failed out of {len(TEST_CASES)} total")
    print("=" * 80)
    
    if errors:
        print()
        print("Failed tests:")
        for error in errors:
            print(f"  {error}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(run_tests())
