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

# Force regenerate lock files even if pyproject.toml hasn't changed
python scripts/update_examples_version.py --version 0.2.0 --force-lock --lock-retries 5

# Dry run to see what would change
python scripts/update_examples_version.py --version 0.2.0 --dry-run
```

**Options:**
- `--version`: New version to set (required unless --force-lock is used)
- `--skip-lock`: Skip regenerating uv.lock files
- `--force-lock`: Force regenerate uv.lock files even if pyproject.toml hasn't changed
- `--lock-retries`: Number of retry attempts for lock regeneration (default: 3)
- `--lock-retry-delay`: Delay in seconds between retries (default: 10)
- `--dry-run`: Show what would be changed without making modifications

**Note on PyPI Propagation:**
When running immediately after publishing to PyPI, the new package version may not be available yet. The script includes retry logic with a delay between retries, but in CI/CD pipelines, it's recommended to:
1. First update `pyproject.toml` files with `--skip-lock`
2. Wait 60-120 seconds for PyPI propagation
3. Then regenerate lock files with increased retry attempts

## update_terraform_versions.py

Updates Terraform module versions for all `yaalalabs/ak-*` modules in `.tf` files.

**Usage:**
```bash
# Update all Terraform module versions
python scripts/update_terraform_versions.py --version 0.2.0-b5

# Dry run to see what would change
python scripts/update_terraform_versions.py --version 0.2.0-b5 --dry-run

# Specify custom directories to search
python scripts/update_terraform_versions.py --version 0.2.0-b5 --directories ak-deployment examples

# Add custom exclusion patterns
python scripts/update_terraform_versions.py --version 0.2.0-b5 --exclude .terraform .backup
```

**Options:**
- `--version`: New version to set for all yaalalabs/ak-* modules (required)
- `--directories`: Directories to search for .tf files (default: ak-deployment examples)
- `--exclude`: Patterns to exclude from search (default: .terraform)
- `--dry-run`: Show what would be changed without making modifications

**What it does:**
- Scans all `.tf` files in specified directories
- Finds module declarations with `source = "yaalalabs/ak-*"` or `source = "app.terraform.io/yaalalabs/ak-*"`
- Updates the corresponding `version` attribute to the specified version
- Skips non-yaalalabs modules (like terraform-aws-modules)
- Excludes `.terraform` directories by default
