# #957: Retire the Azure Functions deployment target — Implementation Spec

This spec lists every edit needed to remove Azure Functions, file by file. The requirements and the three
decisions (delete the docs page, archive the Terraform mirror, remove now) are in [design.md](design.md).
The change only deletes code and rewrites text. It adds no classes, config or dependencies.

_Evidence at `develop` @ `c514f928`. Paths are relative to `ak-py/src/agentkernel/` unless they start
with a top-level folder._

## Design

### Rules for this change

1. **Delete, don't stub.** No `AzureFunctions` placeholder, no friendly-error shim, no redirect page.
   The release note is the only signpost.
2. **Rewrite, don't just delete, where a sentence compares targets.** A table row or list item that names
   Functions next to other targets loses the Functions part; the rest of the sentence stays true.
3. **Point to Container Apps** wherever a reader used to be sent to Functions.
   - Docs link: `deployment/azure-containerized` (`docs/docs/deployment/azure-containerized.md`).
   - Terraform: `yaalalabs/ak-containerized/azurerm`.
   - Example: `examples/azure-containerized/openai-cosmos`.
4. **History stays.** Do not edit `docs/versioned_docs/`, `docs/versioned_sidebars/`, `docs/blog/` or
   `docs/specs/`.

### Python package

| File | Change |
|---|---|
| `deployment/azure/akfunction.py` | Delete. The `AzureFunctions` class, its only content. |
| `deployment/azure/__init__.py` | Delete. Only re-exports `AzureFunctions` (line 12). |
| `azure.py` | Delete. Only `from .deployment.azure import *` (line 8). |
| `ak-py/pyproject.toml:86` | Remove `"azure-functions>=1.24.0,<3.0.0",` from the `azure` extra. |
| `ak-py/uv.lock` | Regenerate with `uv lock`; `azure-functions` drops out. |

- Verified unchanged: nothing else under `ak-py/src` imports `azure.functions`, `agentkernel.azure` or
  `agentkernel.deployment.azure`.
- The other four `azure` extra packages stay; Cosmos DB and the Service Bus transport need them.

### Tests

| File | Change |
|---|---|
| `ak-py/tests/test_azure_function_handler.py` | Delete. Every test targets `AzureFunctions`. |
| `ak-py/tests/test_deployment_identity.py` | Remove `import azure.functions as func` (line 17), the `AzureFunctions` import (line 36), `_azure_request` (line 433) and `class TestAzureFunctions` (lines 438-486). |
| `ak-py/tests/test_payload.py:206-209` | Remove the `akfunction` import and drop it from the module tuple. The test still pins the other three adapters. |

- No new tests. Removing a target needs none; the acceptance grep (see Testing) guards against leftovers.

### Terraform

- Delete `ak-deployment/ak-azure/serverless/` (whole directory).
- `.github/workflows/sync-terraform.yaml:38-41`: remove the `ak-deployment/ak-azure/serverless` matrix entry.
- `scripts/deploy/inject_dependencies.py`:
  - Line 28: remove the `'yaalalabs/ak-serverless/azurerm'` entry from `REGISTRY_TO_LOCAL_ROOTS`.
  - Lines 236-237: remove the `ak-deployment/ak-azure/serverless` branch.
  - Lines 104 and 114: remove `'azure-serverless'` from both type lists.
- README edits:
  - `ak-azure/containerized/README.md:30`: drop `ak-azure/serverless/main.tf` from the list of files that
    pin the provider version.
  - `ak-azure/common/README.md:94,183` and `ak-azure/common/modules/vnet/README.md:12,19,136,201,204-206`:
    the second subnet is now described as the Container Apps subnet. The subnet itself, its name and its
    outputs do not change, because `ak-azure/containerized/state.tf:21-32` reads it.
  - `ak-gcp/serverless/README.md`: drop the Azure Functions column/row from the comparison tables
    (lines 1323, 1364), the "From Azure Functions to GCP Cloud Run" section (line 1401 onward) and the
    link at line 1474.
- Registry mirror (manual, outside this repo, after merge):
  - Push a README notice to `yaalalabs/terraform-azurerm-ak-serverless`: "Retired in Agent Kernel
    <version>. Use `yaalalabs/ak-containerized/azurerm`."
  - Archive the repo. Published versions stay downloadable, so existing pins keep working.

### Examples

- Delete `examples/azure-serverless/` (only `openai/` exists).
- Delete `examples/memory/cosmos/`.
- No port. `examples/azure-containerized/openai-cosmos` already uses `session.type: cosmosdb` on
  Container Apps and is already in the weekly run.
- The other example lock files that list `azure-functions` (`examples/azure-containerized/*/uv.lock`)
  refresh through the existing automated lock-file update job. No hand edit.

### CI

- `.github/integration-test-config.yaml:96-103`: remove both `azure-serverless` entries (memory/cosmos and
  azure-serverless/openai), and the now-empty `# Azure Serverless` comment.
- Remove `'azure-serverless'` from every type check. Each Azure check becomes
  `matrix.type == 'azure-containerized'` or `['azure-containerized']`:
  - `.github/scripts/validate_integration_config.py:65` (`valid_types`). A config that still says
    `azure-serverless` now fails validation, which is what we want.
  - `.github/scripts/run_single_test.py:1071` (argparse `choices`), `:1105`, `:1115`, `:1133`.
  - `.github/workflows/integration-test.yaml:220,228,243,288`.
  - `.github/workflows/integration-test-weekly.yaml:276,303,308`.

### Docs

- Delete `docs/docs/deployment/azure-serverless.md` and remove `'deployment/azure-serverless'` from
  `docs/sidebars.js:84`.
- `docs/docs/deployment/overview.md`:
  - Line 25: remove the `G[Azure Functions<br/>REST]` node (and any edge that uses `G`).
  - Lines 83 and 100: remove the Azure Functions table rows.
  - Lines 199-210: remove the "Azure Serverless" section.
  - Line 274: becomes "**Azure** → **Azure Container Apps** (KEDA scaling, SSE streaming; set
    `container_min_replicas = 0` to scale to zero)". The module allows 0
    (`ak-azure/containerized/variables.tf:174-181`).
  - Lines 318-320: remove the Functions fault-tolerance paragraph and link.
  - Line 351: remove the "Azure Serverless" link.
- `docs/docs/advanced/identity-and-access.md:401-403`: remove the Azure Functions bullet.
- `docs/docs/advanced/scheduling.md:429`: remove "a 400 on Azure Functions," from the list.
- `docs/docs/core-concepts/session.md`: lines 291 and 295 say "Container Apps" instead of Functions;
  remove the "*Azure Functions:*" block at lines 729-735, or relabel it "*Azure Container Apps:*" and
  drop the "caching not recommended" comment line.
- `docs/docs/core-concepts/memory-backends.md:32`: last cell becomes "Container Apps".
- `docs/docs/core-concepts/overview.md:29`: `AWS Lambda / GCP Cloud Run`.
- `docs/docs/examples/overview.md`:
  - Line 103: the `cosmos/` bullet is removed (the example is gone).
  - Lines 147-154: remove the "Azure Serverless Examples" section. It also lists `adk/`, `crewai/` and
    `langgraph/`, which no longer exist.
  - Line 206: remove the Azure Functions bullet.
- `docs/docs/intro.md:97,245,291`: drop Functions from the target list and the Mermaid edge
  (`B -- Azure Cloud --> L["Azure Container Apps"]`); line 291 becomes "AWS Lambda or GCP Cloud Run".
- Website (`docs/src/`):
  - `components/IntegrationsMarquee/data.tsx:136`: remove the Azure Functions item. Line 138 (API
    Management) now links to `/docs/deployment/azure-containerized`.
  - `components/ArchitectureOverview/data.tsx:78`: link to `/docs/deployment/azure-containerized`.
  - `components/AgentKernelArchDiagram/index.tsx:35`: remove the `azfunc` node and any edge that uses it.
  - `components/AgentKernelRuntimeFlowDiagram/index.tsx:16`: `'Azure Container Apps'`.
  - `components/FAQ/index.tsx:82`, `components/FeatureExplorer/data.tsx:243`, `pages/developer.tsx:90,472`,
    `pages/ai-engineer.tsx:106,353`, `pages/features.tsx:883`, `pages/index.tsx:483`: drop Functions from
    each list.
  - `components/Blog/topics.ts:40`: keep. It tags an existing blog post.
- Repo READMEs:
  - `README.md:40,94,232` and `AGENTS.md:36`: drop "Azure Functions" from each target list.
  - `ak-py/README.md:261-305`: delete the "Azure Functions Deployment" section.
  - `ak-py/README.md:327`: "`CloudRun` is the GCP equivalent of `Lambda` (AWS)."

### Skills

- Bundled skills (`skills/`, shipped in the wheel):
  - `ak-cloud-deploy/SKILL.md`:
    - Line 61: remove the `yaalalabs/ak-serverless/azurerm` module choice.
    - Lines 398-399: remove the Azure Functions identity bullet.
    - Lines 1236-1288: remove the "Azure Serverless (Functions + APIM)" section.
    - Line 1657: remove the Functions zip `package_path` note.
    - Line 1672: drop "the Functions app (Azure)" from the identity table cell.
  - `ak-cloud-deploy/evals/evals.json:196`: remove the `deploy-azure-serverless` case.
  - `ak-init/SKILL.md:47`: remove the "Azure Functions" option.
  - `ak-build/SKILL.md:577`: drop "Azure Functions," from the list.
- Dev skills (`.agents/skills/`):
  - `ak-dev-architecture/SKILL.md:35`: drop "Azure Functions" from the adapter list.
  - `ak-dev-architecture/SKILL.md:1014-1016`: remove the `AzureFunctions.handler` sentence.
  - `ak-dev-architecture/SKILL.md:1414`: remove the `azure/` line from the directory tree.
  - `ak-dev-testing-conventions/SKILL.md:123`: remove the `test_azure_function_handler.py` row.

### Release note

- Added to the GitHub release for the version that ships this change, under a "Breaking changes" heading:
  > Azure Functions support is removed: `agentkernel.azure.AzureFunctions`, the `azure-functions`
  > package in the `azure` extra, and the `yaalalabs/ak-serverless/azurerm` Terraform module (now
  > archived). Deploy to Azure Container Apps instead: <link to the azure-containerized guide>.

### Config changes

- None. No `AKConfig` field reads or mentions Azure Functions.

### Behavioural changes

1. `import agentkernel.azure` and `from agentkernel.deployment.azure import ...` raise
   `ModuleNotFoundError`. Intentional (design decision 3).
2. `agentkernel[azure]` installs four packages instead of five. Intentional; nothing else uses
   `azure-functions`.
3. `run_single_test.py --type azure-serverless` is rejected by argparse, and `validate_integration_config.py`
   rejects the type. Intentional, so a stale config fails loudly.
4. `/docs/deployment/azure-serverless` returns 404 on the docs site. Intentional (design decision 1).
   Older versioned copies of the page stay.

**Non-changes:** Container Apps code, its Terraform module and examples; `session.type: cosmosdb`; the
`ak-azure/common` subnet names and outputs; all other deployment targets.

## Error handling

- No new runtime paths, so no new failure modes.
- The one user-facing failure is the import error above. It is plain Python behavior; the release note
  explains it.
- The docs build catches most missed links: a broken page link fails it (`onBrokenLinks: 'throw'`,
  `docs/docusaurus.config.js:27`). A broken `.md` link only warns (`onBrokenMarkdownLinks: 'warn'`,
  line 297), so the leftover greps in Testing are the real guard.

## Testing

- Unit suite: `cd ak-py && uv run pytest` passes. Expected failures from e2e tests that need cloud
  credentials are unrelated (see `AGENTS.md:133`).
- Lint: `make lint-check-all` passes.
- Leftover check, from the repo root:
  ```bash
  grep -rnI "AzureFunctions\|ak-azure/serverless" --exclude-dir=versioned_docs --exclude-dir=specs \
    --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=.terraform .
  grep -rnI "azure-serverless\|azure\.functions\|agentkernel\.azure" --exclude-dir=versioned_docs \
    --exclude-dir=versioned_sidebars --exclude-dir=specs --exclude-dir=node_modules --exclude-dir=.git \
    --exclude-dir=.terraform --exclude='*.lock' .
  ```
  Both return nothing (the second may only show `docs/blog/` and `Blog/topics.ts`, which stay).
- CI config: `python .github/scripts/validate_integration_config.py` passes.
- Docs: `cd docs && npm run build` passes, and its output has no broken-link warnings.
- Weekly integration run: `azure-containerized/openai-cosmos` and `openai-queue-mode` still pass.
