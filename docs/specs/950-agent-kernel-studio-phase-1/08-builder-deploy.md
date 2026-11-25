# 08 · Builder: Deploy tab

| | |
|---|---|
| Artboards | `Builder-Deploy` (main), `Builder-Deploy-NoTarget`, `Builder-Deploy-StateBackend`, `Builder-Deploy-Prerequisites`, `Builder-Deploy-Confirm`, `Builder-Deploy-Applying`, `Builder-Deploy-Done`, `Builder-Deploy-Failed`, `Builder-Deploy-Destroy`, `Builder-Deploy-Redeploy`, `Builder-Deploy-ChangeTarget` |
| Design | Built on the [design canvas](https://claude.ai/artifact/VSewdGFtfYAQe4zGFVt3po), page **Builder**: 9 of 11 artboards. Not drawn yet: `Builder-Deploy-Redeploy`, `Builder-Deploy-ChangeTarget`. |
| Canvas page | Builder |
| Kind | Page with `DesktopShell` |
| Fidelity | Working prototype |
| Story moment | B, ready to ship |
| Read first | [00-project-brief.md](00-project-brief.md) |

## Job

Deploy from this computer. The app generates the Terraform files for one cloud target into `deploy/`, sets up
a remote state backend, checks that the computer is ready, packages the project, shows the Terraform plan, and
applies it only after the user confirms. The same tab redeploys and destroys. The user's own cloud profile is used; the app holds no cloud
credentials.

## Layout

- `DesktopShell` with the Deploy tab active. `DeployStatus` reads "Not deployed".
- A narrow left column: target, cloud account, variables, generated files.
- A wide main column: the deploy as five steps in order, each with its state.
- The bottom panel open on Commands.

## Content

The main artboard shows a first deploy at the moment the plan is ready and waiting for the user.

**Left column**
- Card "Target": the AWS mark, "AWS ECS Fargate · containerized", region eu-west-1, a line "Terraform module
  `yaalalabs/ak-containerized/aws`", and "Change target".
- Card "Cloud account": "AWS profile `default` · account `[ACCOUNT]`", state "Signed in".
- Card "Variables" (`VariableForm`, the variables of `deploy/variables.tf`):

| Variable | Value |
|----------|-------|
| `prefix` | support-triage |
| `region` | eu-west-1 |
| `vpc_id` | `[VPC ID]` |
| `private_subnet_ids` | `[SUBNET IDS]` |
| `alb_security_group_id` | `[SECURITY GROUP]` |
| `ecs_service_security_group_id` | `[SECURITY GROUP]` |
| `openai_api_key` and the other model keys | `SecretChip`: "from .env, passed at run time" |

- Card "Generated files": `deploy/main.tf`, `variables.tf`, `outputs.tf`, `providers.tf`, `terraform.tfvars`,
  `Dockerfile`, `deploy.sh`, each with "View".
- Card "Terraform state": "Remote · S3 bucket `[BUCKET]` · account `[ACCOUNT]`", state "Ready", a line
  "Versioned, encrypted, with state locking", and a link "Use a local file instead".

**Main column: the five steps**

1. **Prerequisites** (passed, collapsed to "7 checks · 1 warning"). Expanded it shows `CheckRow`s:

| Status | Check | Detail | Action |
|--------|-------|--------|--------|
| passed | Terraform | found | |
| passed | Docker | running | |
| passed | AWS credentials | profile `default` is signed in | |
| passed | State backend | S3 bucket `[BUCKET]` is ready | |
| passed | Configuration fits the target | `rest_sync` with `delta` is supported on a single-container ECS service | |
| passed | Tests | 40 of 42 passed | "View" |
| needs a person | Business rules | BR-009 is out of sync · 3 rules have no tests | AI button "Fix with AI" |

2. **Package** (done). `CommandRow`s: `uv export --no-hashes > requirements.txt`,
   `uv pip install -r requirements.txt --target=dist/data`, and the copy of `app.py`, `config.yaml` and the
   `Dockerfile` into `dist/`.
3. **Plan** (ready, waiting for the user). `CommandRow`s `terraform init` and `terraform plan`. A
   `PlanSummary`: "`[N]` to add · 0 to change · 0 to destroy", with a grouped resource list whose rows are
   placeholders (`[resource type] · [name]`). Actions: "View full plan" and a primary "Apply".
4. **Apply** (waiting).
5. **Outputs** (waiting): `agent_invoke_url`.

A card "What will be deployed" above the steps: 3 agents, 4 tools, 3 channels, and the config highlights from
the fixture.

## Behaviour (must work)

- "Apply" opens `Builder-Deploy-Confirm`. Confirming plays `Builder-Deploy-Applying` and ends on
  `Builder-Deploy-Done`.
- "Fix with AI" resolves the business-rules check: "Business rules in sync · fixed by Claude Code".
- "View" on a generated file goes to `Builder-Code`. "View" on Tests goes to `Builder-TestTrace`.
- "Change target" opens `Builder-Deploy-ChangeTarget`.
- On a first deploy with no `deploy/backend.tf`, the tab opens on `Builder-Deploy-StateBackend` before the
  steps. Confirming "Remote" creates the backend, writes `deploy/backend.tf` and continues to the main
  artboard. Choosing "Local file" continues with the Terraform state card showing "Local file in `deploy/`" and
  the note "Keep this file. It is ignored by git. It is lost with this computer."
- A warning does not block applying. A failed check does.
- Every command in the steps also appears in the Commands panel, as it was run.

## States and variants

| Artboard | Pass | Shows |
|----------|------|-------|
| `Builder-Deploy-NoTarget` | first | No `deploy/` folder yet. "Choose where to deploy", with five target cards, one per supported Terraform module: AWS serverless (Lambda and API Gateway), AWS containerized (ECS Fargate), Azure containerized (Container Apps), Google Cloud serverless (Cloud Run, scale to zero), Google Cloud containerized (Cloud Run, always on). Each card says whether it needs Docker. The AI button "Ask Claude Code to set up the deploy". Choosing a card writes `deploy/` and opens the main artboard. |
| `Builder-Deploy-StateBackend` | first | A first deploy, before the steps. A card "Where Terraform keeps its state" with two choices. "Remote (recommended)", selected: "Create S3 bucket `[BUCKET]` in AWS account `[ACCOUNT]`, region eu-west-1, with versioning, encryption and state locking, and write `deploy/backend.tf`." "Local file": "For a scratch deploy only. State stays in `deploy/` on this computer and is lost with it." The literal command the app will run as a `CommandRow`, and a primary "Create backend" that names the account. |
| `Builder-Deploy-Prerequisites` | first | Step 1 open with two failed checks: "Docker is not running" and "AWS profile `default` is not signed in", each with what to do, and "Recheck". Steps 2 to 5 are locked. |
| `Builder-Deploy-Confirm` | first | A `ConfirmModal`: "Apply this plan?", "This creates `[N]` resources in AWS account `[ACCOUNT]`, region eu-west-1, using profile `default`. Cloud resources cost money until you destroy them.", a checkbox "I have reviewed the plan", "Cancel" and "Apply". |
| `Builder-Deploy-Applying` | first | Step 4 running: `terraform apply` as a `CommandRow` with its `LogStream`, a count of resources created so far, and "Stop" with the caution "Stopping can leave some resources created". |
| `Builder-Deploy-Done` | first | All five steps done. Step 5 shows an `OutputList` with `agent_invoke_url` and a copy control, and a ready-made curl request. `DeployStatus` reads "Deployed just now". A danger zone with "Destroy". |
| `Builder-Deploy-Failed` | first | Step 4 failed. The error excerpt from Terraform, "Show log", "Run plan again" and the AI button "Ask Claude Code to diagnose". A note: "Some resources may have been created. A new plan shows the current state." |
| `Builder-Deploy-Destroy` | first | A destructive `ConfirmModal`: "Destroy the deployment?", "This removes every resource this project created in AWS account `[ACCOUNT]`.", a field to type the project name, "Cancel" and "Destroy". It runs `terraform destroy`. A note: "The state bucket `[BUCKET]` is kept. Delete it when you retire the project." |
| `Builder-Deploy-Redeploy` | second | After a first deploy. A card "Changed since the last deploy" lists the changed files. The plan reads "0 to add · `[N]` to change · 0 to destroy". |
| `Builder-Deploy-ChangeTarget` | second | A modal with the five target cards and a warning: "Changing the target replaces the files in `deploy/`. Destroy the current deployment first." |

## Tweaks

- `checks`: all passed, one warning (default), one failed.
- `commands`: bottom panel open or collapsed.

## Handoff notes

- The steps are the real ones: package the project, `terraform init`, `terraform plan`, `terraform apply`,
  `terraform output`, and `terraform destroy` for teardown. They run in `deploy/`.
- The variables differ per Terraform module. Render the form from `deploy/variables.tf`, not from a fixed
  list.
- Model keys are passed to Terraform as variables at run time. They must never be written to
  `terraform.tfvars`.
- "Configuration fits the target" encodes real OAK rules. For example, AWS Lambda rejects `rest_sync` with
  `delta`, and so does AWS ECS in queue mode. A combination the runtime or the Terraform module would reject
  must fail here, before anything is applied.
- Docker is needed by every target that ships a container image: both containerized targets and Google Cloud
  serverless (Cloud Run). AWS serverless needs it only when the Lambda is packaged as an image, not for a zip
  package.
- One deploy target per project in Phase 1. Kubernetes with Helm is not a Terraform target and is not offered.
- Azure Functions is not a target. OAK retired it (issue #957): the `AzureFunctions` handler is gone from
  the package, and the `yaalalabs/ak-serverless/azurerm` module is being withdrawn. Azure deploys go to
  Container Apps.
- The coding agent can write the `deploy/` files through `ak-cloud-deploy`, but it never applies or destroys.
- Remote state is the default. The app creates the backend with the cloud's own command-line tool, in the
  target's account and region, only after a confirmation that names the account, because the backend is real
  infrastructure: an S3 bucket with versioning, encryption and S3 native state locking (`use_lockfile`) on AWS;
  a Cloud Storage bucket with versioning on Google Cloud; a Storage account container on Azure. It writes the
  matching `deploy/backend.tf`, and every command appears in the Commands panel.
- Local state stays available as an explicit choice for scratch deploys, with the warning. "Use a local file
  instead" and the reverse both need a `terraform init` with state migration, which the app runs and shows.
- `terraform destroy` removes the deployment, not the state backend.

## Open details

- Whether a small smoke test of the deployed endpoint belongs here or waits for a later phase.
- How the state bucket is named, and whether one bucket serves several projects in the same account.
