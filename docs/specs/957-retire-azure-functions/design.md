# #957: Retire the Azure Functions deployment target

Agent Kernel stops supporting Azure Functions. We delete its handler, Terraform module, examples, CI
tests and docs. Azure users deploy to Azure Container Apps instead, which already supports everything
Functions does, and more.

_Evidence at `develop` @ `c514f928`. Paths are relative to `ak-py/src/agentkernel/` unless they start
with a top-level folder._

## At a glance

| | Today | After this change |
|---|---|---|
| Ways to run on Azure | Functions or Container Apps | Container Apps only |
| Python entry point | `from agentkernel.azure import AzureFunctions` | Removed; Container Apps uses `RESTAPI.run()` |
| Terraform module | `ak-azure/serverless` and `ak-azure/containerized` | `ak-azure/containerized` only |
| Cosmos DB example | Two: one on Functions, one on Container Apps | The Container Apps one |

- No new code, classes or configuration. This change only deletes and rewrites text.

## Why

- Functions can only run the agent inside the web request. It has no queue path.
  - `AzureFunctions.handler` calls `ChatService.process_chat_request` directly
    (`deployment/azure/akfunction.py:74`).
- That "direct" style is being removed from Agent Kernel, and Functions is listed as a blocker for it.
  - B7 in `docs/specs/remove-direct-mode/research/blockers.md:15` recommends dropping Functions.
- #887 (merged in PR #955) already decided not to give Functions a queue path.
  - `docs/specs/887-azure-queue-mode/design.md:131-134` (G4, option b): "retired with direct mode".
- Container Apps already covers every Functions use case.
  - It runs either in one container, with the in-memory queue, or split into an edge and an agent runner
    over Service Bus (`examples/azure-containerized/openai-queue-mode`).
  - It also supports SSE streaming, which Functions does not
    (`docs/docs/deployment/azure-serverless.md:10`).
- Nothing tracks the retirement today. This issue does.

## What users will notice

- Only people deploying to Azure Functions are affected. Everyone else sees no change.
- `from agentkernel.azure import AzureFunctions` fails after upgrading.
- `pip install agentkernel[azure]` no longer installs the `azure-functions` library.
- The `ak-serverless/azurerm` Terraform module gets no new versions and is marked deprecated.
- The Azure Functions docs page is deleted; links on the site point to the Container Apps guide instead.
- Apps already running on Functions keep running until they upgrade Agent Kernel.

## What changes

### Python package

- Delete `deployment/azure/akfunction.py` (the `AzureFunctions` class).
- Delete the now-empty `deployment/azure/` package and the `agentkernel.azure` shim (`azure.py:8`) that
  re-exports it.
  - Nothing else lives in either; Container Apps does not import them.
- Remove `azure-functions` from the `azure` extra (`ak-py/pyproject.toml:86`) and refresh `ak-py/uv.lock`.
  - Keep `azure-data-tables`, `azure-core`, `azure-servicebus` and `azure-identity`; Cosmos and the
    Service Bus transport use them.

### Tests

- Delete `ak-py/tests/test_azure_function_handler.py`.
- Remove `TestAzureFunctions` and its `_azure_request` helper from
  `ak-py/tests/test_deployment_identity.py:433-486`, plus the `azure.functions` import at the top.
- Drop `akfunction` from the module list in `ak-py/tests/test_payload.py:206-209`.
- Full unit suite still passes.

### Terraform

- Delete `ak-deployment/ak-azure/serverless/`, the whole module.
- Stop syncing it to the registry mirror: remove its entry from `.github/workflows/sync-terraform.yaml:38-41`.
- Remove its mapping from `scripts/deploy/inject_dependencies.py:28` and `:236`.
- Deprecate the mirror repo (`yaalalabs/terraform-azurerm-ak-serverless`): push a last README notice
  pointing to `ak-containerized/azurerm`, then archive the repo.
  - Existing version pins keep working; no new versions are published.
- Keep `ak-azure/common` as is.
  - Its second subnet is named for Functions but Container Apps uses it too
    (`ak-azure/containerized/state.tf:21-32`). Only its README wording changes.

### Examples

- Delete `examples/azure-serverless/` (it holds one example, `openai`).
- Delete `examples/memory/cosmos/`, the Functions + Cosmos DB example.
  - No port needed: `examples/azure-containerized/openai-cosmos` already shows Cosmos DB sessions on
    Container Apps and already runs in the weekly integration run (`.github/integration-test-config.yaml:106-108`).
  - Optionally add a line to the `examples/memory/` index pointing to it.

### CI

- Remove both `azure-serverless` entries from `.github/integration-test-config.yaml:96-103`.
- Remove the `azure-serverless` test type everywhere it is listed, so nobody can add it back by mistake:
  - `.github/scripts/validate_integration_config.py:65`
  - `.github/scripts/run_single_test.py:1071,1105,1115,1133`
  - `.github/workflows/integration-test.yaml:220,228,243,288`
  - `.github/workflows/integration-test-weekly.yaml:276,303,308`
  - `scripts/deploy/inject_dependencies.py:104,114`

### Docs and website

- Delete `docs/docs/deployment/azure-serverless.md` and its sidebar entry (`docs/sidebars.js:84`).
  - Repoint every link to it at the Container Apps guide (`deployment/azure-containerized`), including
    `docs/src/components/IntegrationsMarquee/data.tsx:136,138`,
    `docs/src/components/ArchitectureOverview/data.tsx:78` and `advanced/identity-and-access.md:401`.
- `docs/docs/deployment/overview.md`: remove the Functions rows, boxes and links (lines 25, 83, 100,
  207-210, 274, 318-320, 351).
- Remove or reword Functions mentions in:
  - `ak-py/README.md:261-291` (the "Azure Functions Deployment" section) and `:327` (the `CloudRun` sentence).
  - `README.md:40,94,232` and `AGENTS.md:36`.
  - `docs/docs/intro.md`, `core-concepts/overview.md`, `core-concepts/session.md`,
    `core-concepts/memory-backends.md`, `examples/overview.md`, `advanced/identity-and-access.md`,
    `advanced/scheduling.md`.
  - Website pages and components that list Functions as a target or link to the old page
    (`docs/src/pages/*.tsx`, `docs/src/components/*`).
  - Terraform READMEs: `ak-azure/containerized/README.md:30`, `ak-azure/common/` READMEs,
    `ak-gcp/serverless/README.md` (comparison table, "From Azure Functions" section, link at line 1474).
- Leave alone: `docs/versioned_docs/`, `docs/versioned_sidebars/`, blog posts, and `docs/specs/`.
  They describe the past.

### Skills

- Bundled skills (shipped to users):
  - `ak-cloud-deploy`: delete the "Azure Serverless (Functions + APIM)" section (`SKILL.md:1236-1288`),
    the Functions bullet at `:398`, and the `deploy-azure-serverless` eval (`evals/evals.json:196`).
    An "Azure Functions" request should now lead to Container Apps.
  - `ak-init` (`SKILL.md:47`) and `ak-build` (`SKILL.md:577`): drop Functions from the target lists.
- Dev skills (for contributors):
  - `ak-dev-architecture` (`SKILL.md:35,1014,1414`) and `ak-dev-testing-conventions` (`SKILL.md:123`).

### Release note

- The release note says Azure Functions support was removed, names `AzureFunctions` and
  `ak-serverless/azurerm`, and links to the Container Apps guide.

## Not changing

- Azure Container Apps, its Terraform module, and the Service Bus queue mode from #887.
- Cosmos DB session storage (`type: cosmosdb`); it works the same on Container Apps.
- Azure WebSocket (`async`) support. It stays a gap, as in #887 (G6).
- Old released versions of the package, docs and Terraform module. They stay downloadable.

## Done when

- `grep -rn "AzureFunctions\|ak-azure/serverless" --exclude-dir=versioned_docs --exclude-dir=specs .`
  returns nothing.
- The unit suite passes, and the weekly integration run passes with no `azure-serverless` entries.
- The Container Apps Cosmos example (`azure-containerized/openai-cosmos`) passes the weekly integration run.
- The docs site builds with no broken links to the old page.
- The release note names the removal and links to the Container Apps guide.

## Decisions

1. **Old docs page: delete it.**
   - No stub page. Every link on the site is repointed to the Container Apps guide instead.
2. **Terraform module: README notice, then archive the mirror repo.**
   - Users get a clear signal, and existing version pins keep working.
3. **Timing: remove now, with no deprecation release first.**
   - Agent Kernel is pre-1.0, #887 already pointed users to Container Apps, and the release note covers
     the break.

## Open questions

- None.
