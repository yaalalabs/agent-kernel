---
name: ak-dev-sync-docs-from-branch
description: >
  Sync Agent Kernel documentation from branch changes before a feature or bugfix is merged.
  Use this skill when implementation is ready and you need to inspect new commits plus
  uncommitted changes, then update root docs, ak-py docs, deployment READMEs, example
  READMEs, and the docs website so the documentation matches the implemented behavior.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Sync Documentation From Branch Changes

Use this skill when a feature branch or bugfix branch is functionally ready and you need to align Agent Kernel documentation with what actually changed.

This skill is for **documentation maintenance driven by code diff**, not for implementing the feature itself.

## Goal

Read the branch delta, infer what user-facing and contributor-facing documentation changed, then update the relevant docs across the repository.

Required documentation surfaces covered by this skill:

1. `ak-py/README.md`
2. docs website content under `docs/` — update existing pages, add pages, remove obsolete pages, and adjust intro/getting-started/reference sections as needed
3. README files under `ak-deployment/`
4. example README files when an example was added or changed, plus docs-site references to those examples
5. root `README.md`
6. root `DEVELOPER_GUIDE.md`

## When to Use This Skill

Use this skill when all of the following are true:

1. The developer is on a feature or bugfix branch.
2. The implementation is already done or nearly done.
3. There are new commits on the branch and/or uncommitted local changes.
4. The branch changes behavior, setup, APIs, integrations, deployment flows, examples, capabilities, or contributor workflows in ways documentation should reflect.

Do **not** use this skill as the first step of a feature. Use it near the end, before merge or PR finalization.

## Step 1: Determine the Comparison Base

Find the correct baseline branch first.

Preferred order:

1. The PR target branch if it is known.
2. The upstream tracking branch for the current branch.
3. `origin/develop`.
4. `develop`.

For this repository, prefer `origin/develop` or `develop` as the default base branch unless the PR target or upstream tracking branch says otherwise.

Use Git to identify the merge base between the current branch and that baseline.

Minimum evidence to gather:

- current branch name
- merge base commit
- commits since merge base
- staged changes
- unstaged changes

If the baseline is ambiguous, state the assumption you are using and continue.

## Step 2: Read the Branch Delta

Inspect both committed and uncommitted work.

Required diff inputs:

1. **Committed changes on the branch**
   - commits since merge base
   - file list and diff summary
2. **Current local changes**
   - staged diff
   - unstaged diff

Pay special attention to changes in:

- `ak-py/src/agentkernel/`
- `ak-py/README.md`
- `ak-deployment/`
- `examples/`
- `docs/`
- root `README.md`
- root `DEVELOPER_GUIDE.md`
- tests, examples, and Terraform modules that imply docs drift

## Step 3: Map Code Changes to Documentation Impact

Classify the branch delta into these buckets:

1. **Root-level product docs drift**
   - project overview, supported features, installation, quick start, contributor guidance
   - update `README.md` and `DEVELOPER_GUIDE.md` as needed

2. **Package-level docs drift**
   - Python package install, CLI, skills, APIs, framework support, configuration
   - update `ak-py/README.md`

3. **Docs website drift**
   - new capabilities, changed setup steps, outdated examples, missing pages, obsolete pages
   - update or add/remove pages under `docs/`

4. **Deployment docs drift**
   - Terraform modules, module inputs, deploy flows, packaging changes, environment setup
   - update relevant `ak-deployment/**/README.md` files

5. **Example docs drift**
   - example added, removed, renamed, or behavior changed
   - update example README files and docs-site references to those examples

## Step 4: Required Documentation Surfaces

You must evaluate all of these surfaces before deciding no documentation work is needed:

### Root Docs

- `README.md`
- `DEVELOPER_GUIDE.md`

### Package Docs

- `ak-py/README.md`

### Docs Website

- pages under `docs/docs/`
- related docs metadata such as sidebars or linked overview pages when needed
- intro/getting-started/reference/example pages that are affected by the branch change

### Deployment Docs

- README files under `ak-deployment/`

### Example Docs

- `examples/**/README.md`
- docs-site pages that list, categorize, or link to examples

Do not update only one documentation surface if the same capability is described elsewhere in the repository.

## Step 5: Add, Update, or Remove Documentation

Apply these rules.

### Update Existing Docs When

- the capability already has a documented home
- the branch changes behavior, supported options, configuration, module inputs, examples, or terminology

### Add New Docs or Pages When

- the branch introduces a new reusable workflow, feature area, or example that does not fit cleanly into an existing page
- a new docs page is clearer than overloading an unrelated page

### Remove Docs or Pages When

- the capability or example is no longer supported
- the page is now misleading or fully replaced
- a replacement page or section exists in the same edit

Do not leave stale pages in place once the code path or example has been removed.

## Step 6: Documentation Authoring Rules

When writing or updating docs:

- ground every change in the branch diff and the current implementation
- prefer updating existing pages before creating parallel pages with overlapping scope
- keep terminology consistent with code, config keys, module inputs, and example names
- use current version numbers and current framework/integration names
- align docs examples with live code in `examples/` and `ak-deployment/`
- if an example changed, update both the example README and any docs-site references to it
- if setup steps changed, update both quick-start/getting-started material and deeper reference pages where relevant

## Step 7: Required Files to Consider

Depending on branch impact, review and update files from this list:

- `README.md`
- `DEVELOPER_GUIDE.md`
- `ak-py/README.md`
- `docs/docs/**`
- `docs/sidebars.js`
- `ak-deployment/**/README.md`
- `examples/**/README.md`

Also update docs-site example index pages or overview pages when example inventory changes.

## Step 8: Validation Checklist

Before finishing, validate the documentation sync work.

Minimum validation:

1. Confirm the diff-backed rationale for each documentation update.
2. Verify changed docs still reflect the live code, examples, and module inputs.
3. Check edited markdown/JSON/JS files for diagnostics.
4. Search for stale names, old counts, removed examples, or outdated setup/version references introduced by the branch delta.
5. Confirm example references in the docs site still point to examples that exist.

## Output Expectations

When using this skill, the coding agent should produce:

1. A short branch-impact summary based on commits plus uncommitted changes.
2. A documentation-impact summary by surface:
   - root docs
   - package docs
   - docs website
   - deployment READMEs
   - example READMEs
3. The actual file edits.
4. A validation summary.

## Common Pitfalls

- Updating code or examples without updating the matching README.
- Updating example READMEs but forgetting docs-site references to those examples.
- Updating docs website pages but leaving root or package README content stale.
- Describing behavior from memory instead of checking live code or Terraform inputs.
- Leaving outdated pages in place after capabilities or examples were removed.
- Changing example inventory without updating overview/index pages.

## Quick Heuristic

Use this documentation-sync heuristic:

- **Behavior changed** → patch the docs where that behavior is already explained.
- **New workflow or example appeared** → add or expand docs in every location that should expose it.
- **Workflow or example disappeared** → remove or replace stale docs.
- **Only internal refactoring changed** → no docs change unless contributor guidance is affected.