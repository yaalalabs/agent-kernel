# Scripts

This directory contains utility scripts for the agent-kernel project.

## bump_version.py

Handles semantic versioning for the project with support for:
- Major, minor, and patch version bumps
- Pre-release versions (alpha, beta)
- Automatic pre-release number determination

**Usage:**
```bash
cd ak-py
python ../scripts/bump_version.py --bump patch
python ../scripts/bump_version.py --bump minor --prerelease alpha --auto-prerelease-number
python ../scripts/bump_version.py --bump major --prerelease beta --prerelease-number 2
```

## update_examples_version.py

Updates agentkernel version references in example `pyproject.toml` files and optionally regenerates `uv.lock` files.

**Usage:**
```bash
# Update pyproject.toml files only (skip lock regeneration)
python scripts/update_examples_version.py --version 0.2.0 --skip-lock

# Update pyproject.toml and regenerate lock files with retry logic
python scripts/update_examples_version.py --version 0.2.0 --lock-retries 5 --lock-retry-delay 30

# Dry run to see what would change
python scripts/update_examples_version.py --version 0.2.0 --dry-run
```

**Options:**
- `--version`: New version to set (required)
- `--skip-lock`: Skip regenerating uv.lock files
- `--lock-retries`: Number of retry attempts for lock regeneration (default: 3)
- `--lock-retry-delay`: Delay in seconds between retries (default: 10)
- `--dry-run`: Show what would be changed without making modifications

**Note on PyPI Propagation:**
When running immediately after publishing to PyPI, the new package version may not be available yet. The script includes retry logic with exponential backoff, but in CI/CD pipelines, it's recommended to:
1. First update `pyproject.toml` files with `--skip-lock`
2. Wait 60-120 seconds for PyPI propagation
3. Then regenerate lock files with increased retry attempts

## test_bump_version.py

Unit tests for `bump_version.py`. Can be run directly or as part of a test suite.

**Usage:**
```bash
python scripts/test_bump_version.py
```

**Output:**
```
Running 24 test cases...

✓ Test  1: 0.1.0a1    + patch (alpha ) = 0.1.0a2   
✓ Test  2: 0.1.1a1    + patch (alpha ) = 0.1.1a2   
...
================================================================================
Test Results: 24 passed, 0 failed out of 24 total
================================================================================
```
