# Integration Test Infrastructure

This feature introduces a comprehensive integration testing infrastructure for Agent Kernel, enabling automated end-to-end testing of deployed examples across AWS and Azure platforms. The infrastructure includes test execution framework, structured logging, dependency injection for local development, and CI/CD automation.

## Overview

The integration test infrastructure provides four core capabilities:

1. **Test Execution Framework** - Automated test runner supporting deploy/test/destroy actions for cloud deployments
2. **Structured Logging System** - Logger implementation with configurable levels, structured output, and context propagation
3. **Dependency Injection System** - Automated injection of Terraform backend configuration and local module paths for development
4. **CI/CD Automation** - GitHub Actions workflows for nightly and weekly integration testing with parallel execution

## Test Execution Framework

### Test Runner (`run_single_test.py`)

The test runner provides unified execution for different test types:

**Test Types:**
- `api` - API example tests (build.sh local + pytest)
- `memory` - Memory example tests (build.sh local + pytest)
- `cli` - CLI example tests (build.sh local + pytest)
- `containerized` - Containerized example tests (build.sh local + pytest)
- `aws-serverless` - AWS Lambda deployments (deploy/test/destroy)
- `aws-containerized` - AWS ECS deployments (deploy/test/destroy)
- `azure-serverless` - Azure Functions deployments (deploy/test/destroy)
- `azure-containerized` - Azure Container Apps deployments (deploy/test/destroy)

**Actions:**
- `deploy` - Deploy infrastructure using Terraform
- `test` - Run pytest against deployed endpoint
- `destroy` - Tear down infrastructure

**Key Features:**
- VPC/VNet injection for shared networking infrastructure
- Automatic Terraform output retrieval (agent_invoke_url)
- Environment variable injection (AK_TEST_ENDPOINT)
- Non-interactive Terraform execution (TF_INPUT=0, auto-approve)
- Structured output with status indicators (✅, ❌, ⚠️)

### Base Output Validation (`get_base_outputs.py`)

Retrieves shared infrastructure outputs from base deployments:

- Initializing Terraform in base deployment directory
- Extracting VPC ID and private subnet IDs from Terraform outputs
- Writing outputs to $GITHUB_OUTPUT for workflow consumption
- Validating JSON format for subnet arrays

### Configuration Validation (`validate_integration_config.py`)

Validates integration test configuration:

- YAML syntax validation
- Required tier presence (nightly, weekly)
- Test structure validation (type, path fields)
- Path existence checks
- Deploy directory validation for cloud deployments
- Duplicate test detection
- Valid test type checking

## Dependency Injection System

### Terraform Backend Injection

The dependency injection system (`inject_dependencies.py`) automates local development setup:

**Backend Configuration:**
- Generates `backend.tf` files from templates for each project
- Supports AWS S3 + DynamoDB backend
- Supports Azure Storage backend
- Project-specific state keys based on path
- Reads configuration from `state-config.yaml`

**Module Source Localization:**
- Replaces Terraform registry sources with local relative paths
- Handles `yaalalabs/ak-serverless/aws` → local path
- Handles `yaalalabs/ak-containerized/aws` → local path
- Handles `yaalalabs/ak-serverless/azurerm` → local path
- Handles `yaalalabs/ak-containerized/azurerm` → local path
- Handles `yaalalabs/ak-common/{cloud}//modules/*` → local paths
- Comments out `version` constraints for local modules
- Adds provider markers for reversion tracking

**Reversion:**
- `--revert` flag restores registry sources
- Removes backend.tf files
- Uncomments version constraints
- Removes provider markers

### Backend Setup Script (`setup_backend.sh`)

Creates required cloud infrastructure for Terraform remote state:

**AWS:**
- S3 bucket with versioning and encryption
- DynamoDB table for state locking
- Configurable via CLI args or YAML

**Azure:**
- Resource group
- Storage account with encryption
- Blob container for state
- Configurable via CLI args or YAML

## Structured Logging System

### Logger Implementation

The logger module (`ak-py/src/agentkernel/core/logger.py`) provides:

```python
from agentkernel.core.logger import get_logger

logger = get_logger(__name__)
logger.info("Processing request", extra={"user_id": "123", "action": "login"})
```

### Features

- **Configurable log levels** - DEBUG, INFO, WARNING, ERROR, CRITICAL
- **Structured output** - JSON formatting for machine parsing
- **Context propagation** - Automatic inclusion of request/session context
- **Performance tracking** - Built-in timing and metrics
- **Framework integration** - Works seamlessly with all supported frameworks

### Configuration

Logging is configured via environment variables or config.yaml:

```yaml
logging:
  level: INFO
  format: json
  output: stdout
```

### Integration Points

The logger is integrated throughout the codebase:

- API handlers (HTTP, A2A)
- Framework runners (OpenAI, ADK, CrewAI, LangGraph)
- Deployment handlers (AWS Lambda, Azure Functions)
- Storage backends (DynamoDB, Redis, Cosmos DB)
- Guardrail providers (Bedrock, OpenAI, WalledAI)

## Deployment Infrastructure

### Terraform Output Configurations

Terraform configurations expose outputs needed for testing:

**AWS Serverless:**
- API Gateway endpoint URL
- Lambda function ARN
- Lambda function name
- IAM role ARN

**AWS Containerized:**
- API Gateway endpoint URL
- ECS cluster name
- ECS service name
- Task definition ARN

**Azure Serverless:**
- Function App URL
- Function App name
- Resource group name
- Application Insights instrumentation key

**Azure Containerized:**
- Container App URL
- Container App name
- Resource group name
- Container registry URL

### Deployment Scripts

Deployment scripts (`deploy.sh`, `setup_backend.sh`) provide:

- Better error handling and validation
- Support for multiple backend configurations
- Automatic state management
- Dependency injection for test files

## CI/CD Automation

### Integration Test Workflow

The integration test workflow (`.github/workflows/integration-test.yaml`) provides:

- **Matrix strategy** - Parallel execution across multiple examples
- **Conditional execution** - Run only affected tests based on file changes
- **Better artifact management** - Store test results and logs
- **Failure handling** - Continue on error with detailed reporting

### Weekly Integration Test Workflow

The weekly integration test workflow (`.github/workflows/integration-test-weekly.yaml`) provides:

- **Scheduled execution** - Runs weekly to catch regressions
- **Full test coverage** - Executes all integration tests
- **Notification system** - Alerts on failures
- **Historical tracking** - Maintains test result history

### Configuration Management

Centralized test configuration in `.github/integration-test-config.yaml`:

```yaml
tests:
  - name: aws-serverless-adk
    path: examples/aws-serverless/adk
    platform: aws
    type: serverless
    framework: adk
    
  - name: azure-containerized-openai
    path: examples/azure-containerized/openai-cosmos
    platform: azure
    type: containerized
    framework: openai
```

## Test Files

Test files send prompts to deployed agent endpoints and validate responses:

**Test file types:**
- `lambda_test.py` - AWS Lambda deployments
- `app_test.py` - Containerized deployments (AWS ECS, Azure Container Apps)
- `azure_function_test.py` - Azure Functions deployments

**Test structure:**
```python
async def test_history_agent(http_client):
    response = await http_client.send("when did the battle of Waterloo happen?")
    Test.compare(response, ["The Battle of Waterloo happened on June 18, 1815."], threshold=10)
```

Tests use `AK_TEST_ENDPOINT` environment variable to connect to deployed infrastructure.

## Configuration

### Environment Variables

- `AK_TEST_ENDPOINT` - Agent endpoint URL (set by test runner from Terraform outputs)
- `AK_LOG_LEVEL` - Logging level (default: INFO)
- `AK_LOG_FORMAT` - Log format (json|text, default: json)

## Dependencies

### Python Dependencies

Added to `pyproject.toml`:

- `pytest` - Test framework
- `pytest-asyncio` - Async test support
- `pytest-timeout` - Test timeout management
- `httpx` - HTTP client for API testing

### Lock Files

`uv.lock` files across all examples include new dependencies and resolved version conflicts.

## Documentation

### Configuration Documentation

`docs/docs/core-concepts/configuration.md` documents:

- New logging configuration options
- Environment variable usage
- Testing configuration
- Deployment validation settings

## Implementation Plan

### Task 1: Implement test runner script

**File:** `.github/scripts/run_single_test.py` (new)

1. Create `run_command()` helper for subprocess execution with logging
2. Implement `run_simple_test()` for api/memory/cli/containerized tests
3. Implement `deploy_aws_resources()` with VPC injection support
4. Implement `test_aws_deployment()` with Terraform output retrieval
5. Implement `destroy_aws_resources()` with cleanup
6. Implement `deploy_azure_resources()` with VNet injection support
7. Implement `test_azure_deployment()` with Terraform output retrieval
8. Implement `destroy_azure_resources()` with cleanup
9. Add CLI argument parsing for type, path, action, vpc-id, subnet-ids
10. Add main() function with action routing

---

### Task 2: Implement base output validation script

**File:** `.github/scripts/get_base_outputs.py` (new)

1. Create script to initialize Terraform in base deployment
2. Retrieve vpc_id using `terraform output -raw`
3. Retrieve private_subnet_ids using `terraform output -json`
4. Validate JSON format
5. Write outputs to $GITHUB_OUTPUT
6. Add CLI argument parsing for base-path and deploy-dir

---

### Task 3: Implement configuration validation script

**File:** `.github/scripts/validate_integration_config.py` (new)

1. Load and parse YAML configuration
2. Validate YAML syntax
3. Check required tiers (nightly, weekly)
4. Validate test structure (type, path fields)
5. Check path existence
6. Validate deploy directories for cloud tests
7. Detect duplicate tests
8. Validate test types against allowed list

---

### Task 4: Implement dependency injection system

**File:** `scripts/deploy/inject_dependencies.py` (new)

1. Create `_deployment_tf_files()` to discover .tf files
2. Implement `_localize_registry_source()` to convert registry to local paths
3. Implement `_restore_registry_source()` to convert local back to registry
4. Implement `_rewrite_module_block()` to modify module sources and versions
5. Implement `_rewrite_tf_file()` to process entire files
6. Create `inject_dependencies()` entry point
7. Create `revert_dependencies()` entry point
8. Implement `generate_backend_tf()` for template substitution
9. Implement `inject_backend_files()` to create backend.tf files
10. Implement `remove_backend_files()` for cleanup
11. Add CLI argument parsing for --revert flag
12. Load configuration from YAML files

---

### Task 5: Implement backend setup script

**File:** `scripts/deploy/setup_backend.sh` (new)

1. Create `setup_aws()` function for S3 + DynamoDB
2. Create `setup_azure()` function for Storage Account + Container
3. Add CLI argument parsing for cloud selection and overrides
4. Load defaults from state-config.yaml using yq
5. Add help documentation
6. Implement resource existence checks
7. Add configuration output examples

---

### Task 6: Create backend templates and configuration

**Files:** `scripts/deploy/backend.tf.aws.template`, `scripts/deploy/backend.tf.azure.template`, `scripts/deploy/state-config.yaml` (new)

1. Create AWS S3 backend template with placeholders
2. Create Azure Storage backend template with placeholders
3. Create state-config.yaml with AWS and Azure defaults
4. Document configuration structure in README.md

---

### Task 7: Implement structured logging system

**File:** `ak-py/src/agentkernel/core/logger.py` (new)

1. Create `get_logger(name: str)` function
2. Implement JSON formatter for structured logging
3. Add context manager for request/session context propagation
4. Implement log level configuration from environment variables
5. Export from `ak-py/src/agentkernel/core/__init__.py`

**File:** `ak-py/tests/test_ak_logger.py` (new)

1. Test logger creation and configuration
2. Test log level filtering
3. Test JSON formatting
4. Test context propagation
5. Test error handling

---

### Task 8: Integrate logger throughout codebase

**Files:** Multiple files across `ak-py/src/agentkernel/`

1. Add logger to API handlers (HTTP, A2A)
2. Add logger to framework runners (OpenAI, ADK, CrewAI, LangGraph)
3. Add logger to deployment handlers (AWS Lambda, Azure Functions)
4. Add logger to storage backends (DynamoDB, Redis, Cosmos DB, SessionCache)
5. Add logger to guardrail providers (Bedrock, OpenAI)
6. Remove WalledAI guardrail logging (deprecated)

---

### Task 9: Create integration test configuration

**File:** `.github/integration-test-config.yaml` (new)

1. Define deployment_base section for shared infrastructure
2. Define nightly tier with test configurations
3. Define weekly tier with test configurations
4. Specify test type, path, and deploy_dir for each test

---

### Task 10: Create GitHub Actions workflows

**Files:** `.github/workflows/integration-test.yaml`, `.github/workflows/integration-test-weekly.yaml` (new)

1. Create nightly workflow with matrix strategy
2. Create weekly workflow with matrix strategy
3. Implement base deployment step
4. Implement parallel test execution with VPC/VNet injection
5. Add deployment cleanup steps
6. Configure artifact upload for test results

---

### Task 11: Add Terraform outputs

**Files:** Multiple `outputs.tf` files across deployments

1. Add `agent_invoke_url` output for all deployments
2. Add `vpc_id` output for AWS base deployments
3. Add `private_subnet_ids` output for AWS base deployments
4. Add `vnet_id` output for Azure base deployments (if applicable)
5. Add `subnet_ids` output for Azure base deployments (if applicable)

---

### Task 12: Create test files

**Files:** Multiple `*_test.py` files across examples

1. Create `app_test.py` for AWS/Azure containerized deployments
2. Create `lambda_test.py` for AWS serverless deployments
3. Create `azure_function_test.py` for Azure serverless deployments
4. Implement endpoint tests using AK_TEST_ENDPOINT
5. Add pytest configuration with junitxml output

---

### Task 13: Add dependencies

**Files:** Multiple `pyproject.toml` and `uv.lock` files

1. Add pytest to all example projects
2. Add httpx for HTTP client testing (where needed)
3. Update uv.lock files across all examples
4. Resolve dependency conflicts

---

### Task 14: Update documentation

**File:** `docs/docs/core-concepts/configuration.md`

1. Document logging configuration options
2. Document environment variables (AK_LOG_LEVEL, AK_LOG_FORMAT)
3. Add configuration examples

**File:** `scripts/deploy/README.md` (new)

1. Document dependency injection system
2. Document backend setup process
3. Provide usage examples
4. Explain what gets modified

---

### Task 15: Update .gitignore

**File:** `.gitignore`

1. Add pytest cache directories (`__pycache__`, `.pytest_cache`)
2. Add test report files (`pytest-report.xml`)
3. Add Terraform state files for testing
4. Add backend.tf (generated files)

## Error Handling

- Logger initialization failures fall back to standard Python logging
- Missing Terraform outputs cause test failures with clear error messages
- Test runner exits with non-zero code on failures
- CI/CD workflow failures include detailed error context

## Testing Strategy

### Integration Tests

- Deploy infrastructure using Terraform
- Retrieve agent endpoint URL from Terraform outputs
- Send test prompts to agent endpoint
- Validate agent responses using fuzzy matching
- Tests maintain session state for follow-up questions
- Tear down infrastructure after tests complete
