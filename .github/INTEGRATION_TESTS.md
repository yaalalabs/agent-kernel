# Integration Test Framework - Setup Summary

## Created Files

### 1. Configuration File
**Location:** [`.github/integration-test-config.yaml`](.github/integration-test-config.yaml)

Defines which tests run in nightly vs weekly tiers and their execution order. This is the single source of truth for test configuration.

**Features:**
- Separate test lists for nightly and weekly tiers
- Ordered execution
- Support for multiple test types: `api`, `memory`, `aws-containerized`, `aws-serverless`
- Easy to add/remove/reorder tests

### 2. GitHub Actions Workflows

#### Nightly Tests
**Location:** [`.github/workflows/integration-test.yaml`](.github/workflows/integration-test.yaml)

- **Schedule:** Daily at 2 AM UTC (`0 2 * * *`)
- **Behavior:** Runs all tests, but for AWS projects only executes deploy and test (no resource destruction)
- **Manual Trigger:** Available via GitHub Actions UI

#### Weekly Tests
**Location:** [`.github/workflows/integration-test-weekly.yaml`](.github/workflows/integration-test-weekly.yaml)

- **Schedule:** Every Sunday at 3 AM UTC (`0 3 * * 0`)
- **Behavior:** Full lifecycle testing - destroys all AWS resources first, then deploys and tests each project
- **Manual Trigger:** Available via GitHub Actions UI

### 3. Matrix Generator
**Location:** [`.github/scripts/generate_test_matrix.py`](.github/scripts/generate_test_matrix.py)

Generates test matrices for GitHub Actions workflows from the configuration file.

**Features:**
- Generates matrices for both nightly and weekly tiers
- Nightly: Excludes `aws-serverless/openai` (runs separately)
- Weekly: Generates both full test matrix and AWS-only matrix
- Output formats: JSON or GitHub Actions format

**Usage:**
```bash
# Nightly matrix (JSON format)
python3 .github/scripts/generate_test_matrix.py --tier nightly --format json

# Weekly matrices (GitHub format)
python3 .github/scripts/generate_test_matrix.py --tier weekly --format github
```

### 4. Test Runner Script
**Location:** [`.github/scripts/run_single_test.py`](.github/scripts/run_single_test.py)

Python script that runs a single test. Used by the parallel GitHub Actions jobs.

**Features:**
- Runs individual tests (api, memory, aws-containerized, aws-serverless)
- Supports both `test` and `destroy` actions
- Used by GitHub Actions matrix strategy for parallel execution
- Detailed logging and error reporting

**Usage:**
```bash
# Run a test
python .github/scripts/run_single_test.py --type api --path examples/api/openai --action test

# Destroy AWS resources
python .github/scripts/run_single_test.py --type aws-serverless --path examples/aws-serverless/openai --action destroy
```

### 4. Configuration Validator
**Location:** [`.github/scripts/validate_integration_config.py`](.github/scripts/validate_integration_config.py)

Validates the configuration file for:
- Valid YAML syntax
- Required tiers present
- Valid test types
- Path existence
- Duplicate detection

**Usage:**
```bash
python .github/scripts/validate_integration_config.py
```

### Weekly Tests
Same as nightly, but with full AWS resource lifecycle (destroy → deploy → test).
The workflows use OIDC to assume the IAM role for AWS access, which is more secure than storing access keys.

## Maintenance

### Adding a New Test
Edit [`.github/integration-test-config.yaml`](.github/integration-test-config.yaml):
```yaml
nightly:
  tests:
    # ... existing tests ...
    - type: api
      path: examples/api/my-new-example
```

### Changing Test Order
Simply reorder entries in the config file.

### Changing Schedule
Edit the cron expressions in:
- [`.github/workflows/integration-test.yaml`](.github/workflows/integration-test.yaml) (nightly)
- [`.github/workflows/integration-test-weekly.yaml`](.github/workflows/integration-test-weekly.yaml) (weekly)

## Validation

Run the validator before committing config changes:
```bash
python3 .github/scripts/validate_integration_config.py
```

