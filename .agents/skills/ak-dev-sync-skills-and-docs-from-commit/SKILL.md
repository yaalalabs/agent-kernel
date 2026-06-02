---
name: ak-dev-sync-skills-and-docs-from-commit
description: >
  Sync Agent Kernel skills and documentation from a specific commit hash.
  Use this skill in automation or maintenance flows to analyze code changes introduced
  by a commit, then update developer skills, user skills, and docs surfaces so the
  repository guidance stays aligned with implementation.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Sync Skills and Docs From Commit Hash

Use this skill to process a specific commit hash and synchronize both skill trees and documentation based on what changed in that commit.

This skill combines the intent of:

- `ak-dev-sync-skills-from-branch`
- `ak-dev-sync-docs-from-branch`

but uses a **commit hash as the primary unit of analysis**.

## Goal

Given a commit hash (typically on `develop` after PR merge), analyze the introduced code changes and update:

- developer skills under `.agents/skills/`
- user skills under `ak-py/src/agentkernel/skills/`
- documentation surfaces including root docs, package docs, docs website, deployment READMEs, and example READMEs

## Primary Automation Context

This skill is intended for GitHub Actions automation when a commit lands on `develop` from a merged PR.

Expected automation behavior:

1. Trigger on push to `develop`.
2. Ignore direct commits and ignore bot/app-driven commits.
3. Resolve PR metadata associated with the pushed commit hash.
4. Run this skill against that commit hash.
5. Commit generated skill/docs updates to an automation branch.
6. Open a PR for human review.
7. Human approves and merges.
8. Future runs ignore automation-generated sync PR commits to prevent circular updates.

## Inputs

Required:

- `commit_sha`: full SHA of the commit to analyze

Optional but recommended:

- `base_branch`: default `develop`
- `repo_owner`
- `repo_name`
- `associated_pr_number`

## Step 1: Validate Commit Eligibility

Before analyzing, validate that this commit should be processed.

Skip processing when any of the following is true:

1. Commit is not on `develop`.
2. Commit is from a bot/app actor (for example `github-actions[bot]` or any `*[bot]`).
3. Commit is not associated with a merged PR into `develop` (direct push or manual commit).
4. Commit belongs to an automation-generated sync PR (loop prevention).
   - Example loop markers:
     - PR label: `auto-skill-doc-sync`
     - automation branch prefix: `auto/skill-doc-sync/`
     - title prefix: `chore(auto): sync skills/docs`

If skipped, return a clear reason and perform no edits.

## Step 2: Build the Commit Delta

Analyze the commit delta with respect to its first parent.

Minimum required evidence:

- changed file list
- diff summary
- affected capability areas (frameworks, integrations, deployment, docs, tests, examples)

Also include current uncommitted workspace changes **only if** the invocation explicitly asks for commit+workspace mode. Default mode is commit-only.

In commit+workspace mode, gather:

- staged diff
- unstaged diff

and evaluate them alongside the commit delta.

## Step 3: Map Delta to Skill Impact

Classify skill impact from the commit:

1. **Developer skill impact**
   - update existing `.agents` skills
   - add new developer skill for new reusable contributor workflow
   - remove obsolete developer skill if capability is removed/replaced

2. **User skill impact**
   - update existing user skills in `ak-py/src/agentkernel/skills/`
   - update/add/remove evals under `ak-py/src/agentkernel/skills/*/evals/evals.json`
   - add/remove user skills only when workflow boundaries actually changed

3. **Behavior drift in an existing skill**
  - configuration keys changed, module inputs changed, supported backends changed, examples changed, packaging changed
  - patch the existing skill instead of creating a new one

4. **Capability removal or consolidation**
  - path is deprecated or replaced by another workflow
  - remove or merge obsolete skill only if replacement is clear and documented

### Skill Decision Rules

#### Add a New Developer Skill When

- commit introduces a repeatable contributor task
- task spans multiple files or subsystems
- contributors would otherwise need architecture/context not obvious from local code
- workflow is likely reusable in future changes

#### Update an Existing Developer Skill When

- commit extends or changes an already-covered contributor workflow
- new work fits naturally inside an existing skill scope

#### Add a New User Skill When

- commit creates a new reusable user-facing workflow
- workflow cannot be represented as a small subsection in an existing user skill

#### Update an Existing User Skill When

- commit changes supported options, code templates, config, examples, or eval expectations
- workflow belongs to existing user skill set (`ak-init`, `ak-build`, `ak-add-capabilities`, `ak-add-integration`, `ak-cloud-deploy`, `ak-test`)

#### Remove a Skill When

- capability is no longer supported
- no documented example or implementation path remains
- replacement skill or replacement workflow is identified in the same change

Do not remove a skill only because the specific commit did not touch that area.

### Keep Both Skill Trees in Sync

Whenever commit changes justify skill updates, inspect both:

- developer skills: `.agents/skills/`
- user skills: `ak-py/src/agentkernel/skills/`

Do not stop after one side if the capability impact clearly affects both contributor and end-user workflows.

## Step 4: Map Delta to Documentation Impact

Evaluate and update all relevant documentation surfaces:

1. `ak-py/README.md`
2. docs website pages under `docs/` (including intro/getting-started/reference and example pages)
3. README files under `ak-deployment/`
4. changed/new example READMEs under `examples/` plus docs-site references to those examples
5. root `README.md`
6. root `DEVELOPER_GUIDE.md`

If a docs page becomes obsolete because a capability was removed, remove or replace it in the same change.

### Documentation Decision Rules

#### Update Existing Docs When

- capability already has a documented home
- commit changes behavior, supported options, config, module inputs, examples, or terminology

#### Add New Docs or Pages When

- commit introduces a new reusable workflow, feature area, or example that does not fit cleanly into existing pages
- a dedicated page is clearer than overloading an unrelated page

#### Remove Docs or Pages When

- capability or example is no longer supported
- page is now misleading or fully replaced
- replacement page or replacement section exists in the same change

Do not leave stale docs pages in place once code path or example has been removed.

## Step 5: Required Inventory/Catalog Sync

If developer skill inventory changes, update:

- `docs/docs/agent-skills.md`
- `docs/specs/agent-skills.md`

Ensure skill counts, tables, and file inventories match `.agents/skills/` exactly.

Also update other contributor docs if they explicitly enumerate developer skills.

## Step 6: Required Files to Consider

Depending on commit impact, review and update files from this list.

Skill files:

- `.agents/skills/*/SKILL.md`
- `ak-py/src/agentkernel/skills/*/SKILL.md`
- `ak-py/src/agentkernel/skills/*/evals/evals.json`

Documentation files:

- `README.md`
- `DEVELOPER_GUIDE.md`
- `ak-py/README.md`
- `docs/docs/**`
- `docs/sidebars.js`
- `ak-deployment/**/README.md`
- `examples/**/README.md`

If example inventory changed, update docs-site overview/index pages that reference examples.

## Step 7: Authoring Rules

- Ground every update in the commit diff.
- Keep skill scopes non-overlapping.
- Prefer patching existing skills/docs over creating duplicates.
- Use current config keys, module inputs, example paths, and versions.
- Ensure docs examples are executable against current code.
- Keep loop-prevention markers documented for automation flows.
- Include gotchas only when they are real and recurring.
- Keep examples aligned with live code in `examples/` and `ak-deployment/`.
- If an example changed, update both its README and docs-site references.
- If setup steps changed, update both quick-start/getting-started and deeper reference pages where relevant.

## Step 8: Validation Checklist

Minimum validation before opening PR:

1. Confirm every change is traceable to the analyzed commit.
2. Validate edited JSON files parse.
3. Check edited markdown/JSON/workflow files for diagnostics.
4. Verify docs/spec skill counts match actual `.agents/skills/` directories.
5. Verify example references in docs site point to existing examples.
6. Confirm automation loop markers remain in workflow logic and PR metadata.
7. Search for stale capability names, old counts, removed examples, or outdated setup/version references introduced by the commit delta.

## Output Expectations

When this skill runs successfully, produce:

1. Commit-impact summary.
2. Skill-impact summary (developer and user skill updates).
3. Documentation-impact summary.
4. List of edited files.
5. Validation results.

## Common Pitfalls

- Treating direct pushes to `develop` as PR commits.
- Failing to ignore bot/app commits.
- Forgetting loop-prevention filters for auto-generated sync PRs.
- Updating skills but not documentation, or documentation but not skills.
- Updating docs references to examples without updating the example README (or vice versa).
- Updating only one documentation surface when the same capability appears in multiple surfaces.
- Describing behavior from memory instead of checking live code, examples, or Terraform inputs.

## Quick Heuristic

- **Commit changes behavior/capability** → update affected skills and docs.
- **Commit introduces new reusable workflow** → add skill(s) and docs section/page.
- **Commit removes workflow** → remove/replace stale skill/docs content.
- **Commit is automation-sync output** → skip to avoid circular updates.
- **Only one-off internal refactoring changed** → no docs/skills changes unless contributor guidance is affected.