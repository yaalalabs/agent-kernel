# 08 · Builder: Deploy tab

| | |
|---|---|
| Artboards | `Builder-Deploy` (main), `Builder-Deploy-NoTarget`, `Builder-Deploy-Prerequisites`, `Builder-Deploy-Confirm`, `Builder-Deploy-Applying`, `Builder-Deploy-Done`, `Builder-Deploy-Failed`, `Builder-Deploy-Destroy`, `Builder-Deploy-Redeploy`, `Builder-Deploy-ChangeTarget` |
| Design | Built on the [design canvas](https://claude.ai/artifact/VSewdGFtfYAQe4zGFVt3po), page **Builder**: 8 of 10 artboards. Not drawn yet: `Builder-Deploy-Redeploy`, `Builder-Deploy-ChangeTarget`. |
| Canvas page | Builder |
| Kind | Page with `DesktopShell` |
| Fidelity | Working prototype |
| Story moment | B, ready to ship |
| Read first | [00-project-brief.md](00-project-brief.md) |

## Job

Deploy from this computer. The app generates the Terraform files for one cloud target into `deploy/`, checks
that the computer is ready, packages the project, shows the Terraform plan, and applies it only after the user
confirms. The same tab redeploys and destroys. The user's own cloud profile is used; the app holds no cloud
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
- Card "Terraform state": "Local file in `deploy/`", a note "Keep this file. It is ignored by git.", and a link
  "Use a remote backend".

**Main column: the five steps**

1. **Prerequisites** (passed, collapsed to "6 checks · 1 warning"). Expanded it shows `CheckRow`s:

| Status | Check | Detail | Action |
|--------|-------|--------|--------|
| passed | Terraform | found | |
| passed | Docker | running | |
| passed | AWS credentials | profile `default` is signed in | |
| passed | Configuration fits the target | `rest_sync` with `delta` is supported on a single-container ECS service | |
| passed | Tests | 40 of 42 passed | "View" |
| needs a person | Business rules | BR-009 is out of sync | AI button "Fix with AI" |

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
- A warning does not block applying. A failed check does.
- Every command in the steps also appears in the Commands panel, as it was run.

## States and variants

| Artboard | Pass | Shows |
|----------|------|-------|
| `Builder-Deploy-NoTarget` | first | No `deploy/` folder yet. "Choose where to deploy", with six target cards, one per Terraform module: AWS serverless (Lambda and API Gateway), AWS containerized (ECS Fargate), Azure serverless (Functions), Azure containerized (Container Apps), Google Cloud serverless (Cloud Run, scale to zero), Google Cloud containerized (Cloud Run, always on). Each card says whether it needs Docker. The AI button "Ask Claude Code to set up the deploy". Choosing a card writes `deploy/` and opens the main artboard. |
| `Builder-Deploy-Prerequisites` | first | Step 1 open with two failed checks: "Docker is not running" and "AWS profile `default` is not signed in", each with what to do, and "Recheck". Steps 2 to 5 are locked. |
| `Builder-Deploy-Confirm` | first | A `ConfirmModal`: "Apply this plan?", "This creates `[N]` resources in AWS account `[ACCOUNT]`, region eu-west-1, using profile `default`. Cloud resources cost money until you destroy them.", a checkbox "I have reviewed the plan", "Cancel" and "Apply". |
| `Builder-Deploy-Applying` | first | Step 4 running: `terraform apply` as a `CommandRow` with its `LogStream`, a count of resources created so far, and "Stop" with the caution "Stopping can leave some resources created". |
| `Builder-Deploy-Done` | first | All five steps done. Step 5 shows an `OutputList` with `agent_invoke_url` and a copy control, and a ready-made curl request. `DeployStatus` reads "Deployed just now". A danger zone with "Destroy". |
| `Builder-Deploy-Failed` | first | Step 4 failed. The error excerpt from Terraform, "Show log", "Run plan again" and the AI button "Ask Claude Code to diagnose". A note: "Some resources may have been created. A new plan shows the current state." |
| `Builder-Deploy-Destroy` | first | A destructive `ConfirmModal`: "Destroy the deployment?", "This removes every resource this project created in AWS account `[ACCOUNT]`.", a field to type the project name, "Cancel" and "Destroy". It runs `terraform destroy`. |
| `Builder-Deploy-Redeploy` | second | After a first deploy. A card "Changed since the last deploy" lists the changed files. The plan reads "0 to add · `[N]` to change · 0 to destroy". |
| `Builder-Deploy-ChangeTarget` | second | A modal with the six target cards and a warning: "Changing the target replaces the files in `deploy/`. Destroy the current deployment first." |

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
- "Configuration fits the target" encodes real Agent Kernel rules. For example, AWS Lambda rejects
  `rest_sync` with `delta`. A combination the runtime would reject must fail here, before anything is applied.
- Docker is needed for containerized targets only.
- One deploy target per project in Phase 1. Kubernetes with Helm is not a Terraform target and is not offered.
- The coding agent can write the `deploy/` files through `ak-cloud-deploy`, but it never applies or destroys.

## Open details

- Whether a small smoke test of the deployed endpoint belongs here or waits for a later phase.
