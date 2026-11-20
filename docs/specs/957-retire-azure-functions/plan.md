# #957: Retire the Azure Functions deployment target — Implementation Plan

One PR. Each iteration leaves the branch working. Section names refer to [spec.md](spec.md).

## Iteration 1: Remove the Python target

- **Goal:** the package no longer ships `AzureFunctions`, and the unit suite passes.
- **Files:** `deployment/azure/`, `azure.py`, `ak-py/pyproject.toml`, `ak-py/uv.lock`, the three test files.
- **Steps:**
  1. Delete the code and edit `pyproject.toml` (spec: Python package).
  2. Delete or edit the tests (spec: Tests).
  3. Run `uv lock` in `ak-py/`.
- **Verify:** `cd ak-py && uv run pytest` and `make lint-check-all`.

## Iteration 2: Remove the examples and CI entries

- **Goal:** no test config, workflow or script knows about `azure-serverless`.
- **Files:** `examples/azure-serverless/`, `examples/memory/cosmos/`, `.github/integration-test-config.yaml`,
  `.github/scripts/*.py`, `.github/workflows/integration-test*.yaml`.
- **Steps:**
  1. Delete both example folders (spec: Examples).
  2. Remove the config entries and every `azure-serverless` type check (spec: CI).
- **Verify:** `python .github/scripts/validate_integration_config.py` passes.

## Iteration 3: Remove the Terraform module

- **Goal:** `ak-azure/serverless` is gone and nothing syncs or maps it.
- **Files:** `ak-deployment/ak-azure/serverless/`, `.github/workflows/sync-terraform.yaml`,
  `scripts/deploy/inject_dependencies.py`, the Terraform READMEs.
- **Steps:** follow spec: Terraform, except the registry-mirror steps (those are in Iteration 6).
- **Verify:** `grep -rn "ak-azure/serverless\|ak-serverless/azurerm" ak-deployment scripts .github` is empty.

## Iteration 4: Sync docs and skills

- **Goal:** no doc, website page or skill points users at Functions.
- **Files:** everything under spec: Docs and spec: Skills.
- **Steps:**
  1. Delete the docs page and sidebar entry; repoint its links.
  2. Edit the docs, website pages and READMEs.
  3. Edit the bundled skills (`ak-cloud-deploy`, `ak-init`, `ak-build`) and the dev skills
     (`ak-dev-architecture`, `ak-dev-testing-conventions`).
  4. Run the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` flows to catch anything
     missed.
- **Verify:** `cd docs && npm run build` passes.

## Iteration 5: Tests

- **Goal:** the whole change is checked end to end.
- **Steps:** run every check in spec: Testing (unit suite, lint, both leftover greps, config validation).
- **Verify:** all pass. Trigger a manual weekly integration run for the two Azure Container Apps examples.

## Iteration 6: After merge

- **Goal:** users get the signal.
- **Steps:**
  1. Add the release note (spec: Release note) to the next GitHub release.
  2. Push the README notice to `yaalalabs/terraform-azurerm-ak-serverless`, then archive the repo.
  3. Close #957 and tick B7 in the remove-direct-mode epic.
- **Verify:** the registry page shows the notice; the release note links to the Container Apps guide.
