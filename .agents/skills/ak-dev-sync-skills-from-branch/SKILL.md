---
name: ak-dev-sync-skills-from-branch
description: >
  Sync Agent Kernel skills from branch changes before a feature or bugfix is merged.
  Use this skill when implementation is ready and you need to inspect new commits plus
  uncommitted changes, then update developer skills under .agents and user skills under
  ak-py/src/agentkernel/skills to match the actual capability set.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Sync Skills From Branch Changes

Use this skill when a feature branch or bugfix branch is functionally ready and you need to align Agent Kernel's skills with what actually changed.

This skill is for **skill maintenance driven by code diff**, not for implementing the feature itself.

## Goal

Read the branch delta, infer what contributor-facing and user-facing capabilities changed, then:

- update existing developer skills under `.agents/skills/`
- add new developer skills if a new reusable contributor workflow now exists
- update existing user skills under `ak-py/src/agentkernel/skills/`
- add new user skills if a new reusable end-user workflow now exists
- remove obsolete skills only when the codebase no longer supports that capability and no replacement path remains
- update evals and skill catalogs/docs so the inventory remains consistent

## When to Use This Skill

Use this skill when all of the following are true:

1. The developer is on a feature or bugfix branch.
2. The implementation is already done or nearly done.
3. There are new commits on the branch and/or uncommitted local changes.
4. The change may affect capabilities, workflows, supported integrations, deployment paths, contributor workflows, or examples.

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
- `.agents/skills/`
- `ak-py/src/agentkernel/skills/`
- `examples/`
- `ak-deployment/`
- `docs/`
- tests and evals

## Step 3: Convert Code Changes Into Skill Impact

Classify the branch delta into these buckets:

1. **New contributor workflow**
   - Example: a new extension surface, new adapter type, new storage/provider/integration pattern.
   - Result: add or expand a developer skill under `.agents/skills/`.

2. **New end-user workflow**
   - Example: a new deploy mode, capability, integration, framework, or testing path that users can adopt in their own projects.
   - Result: add or expand a user skill under `ak-py/src/agentkernel/skills/`.

3. **Behavior drift in an existing skill**
   - Example: configuration keys changed, module inputs changed, supported backends changed, examples changed, packaging changed.
   - Result: patch the existing skill instead of creating a new one.

4. **Capability removal or consolidation**
   - Example: a path is deprecated or replaced by another workflow.
   - Result: remove or merge the obsolete skill only if the replacement is clear and documented.

## Step 4: Decide Whether to Add, Update, or Remove Skills

Apply these rules.

### Add a New Developer Skill When

- the branch introduces a **repeatable contributor task**
- that task spans multiple files or subsystems
- contributors would otherwise need architecture/context not obvious from local code
- the workflow is likely to be reused for future features

### Update an Existing Developer Skill When

- the branch extends or changes an already-covered contributor workflow
- the new work fits naturally into an existing skill's scope

### Add a New User Skill When

- the branch creates a new reusable user-facing workflow
- that workflow cannot be explained as a small subsection inside an existing user skill

### Update an Existing User Skill When

- the branch changes supported options, code templates, configuration, examples, or eval expectations
- the workflow already belongs to one of the existing user skills (`ak-init`, `ak-build`, `ak-add-capabilities`, `ak-add-integration`, `ak-cloud-deploy`, `ak-test`)

### Remove a Skill When

- the capability is no longer supported
- no documented example or implementation path remains
- a replacement skill or replacement workflow is identified in the same edit

Do not remove a skill just because the current branch did not touch that area.

## Step 5: Update Both Skill Trees Together

Whenever branch changes justify skill work, inspect **both** locations:

- developer skills: `.agents/skills/`
- user skills: `ak-py/src/agentkernel/skills/`

Do not stop after updating only one side if the branch change clearly affects both contributor and end-user workflows.

Examples:

- A new pluggable subsystem may need:
  - a developer skill explaining how contributors add new implementations
  - a user skill update explaining how users enable or consume that subsystem
- A new integration may need:
  - a developer skill update for extending integrations
  - a user skill update for enabling the new integration

## Step 6: Required Files to Consider

After deciding the skill impact, update the relevant files from this list.

Potential developer-skill files:

- `.agents/skills/*/SKILL.md`

Potential user-skill files:

- `ak-py/src/agentkernel/skills/*/SKILL.md`
- `ak-py/src/agentkernel/skills/*/evals/evals.json`

Required inventory/docs files when the skill set changes:

- `docs/docs/agent-skills.md`
- `docs/specs/agent-skills.md`

Also update other contributor docs if they explicitly enumerate developer skills.

## Step 7: Skill Authoring Rules

When writing or updating skills:

- prefer extending an existing skill over creating overlapping skills
- keep scope narrow and reusable
- ground instructions in real code paths, examples, and current module inputs
- use current versions and current configuration keys
- include gotchas only when they are real and recurring
- keep examples aligned with live examples in `examples/` or `ak-deployment/`
- update evals when user skills change materially

## Step 8: Validation Checklist

Before finishing, validate the skill sync work.

Minimum validation:

1. Confirm the diff-backed rationale for every added/updated/removed skill.
2. Check that user-skill eval JSON still parses.
3. Check edited markdown/JSON files for diagnostics.
4. Verify skill inventory counts and tables in docs/specs match the actual `.agents/skills/` directory.
5. Search for stale capability names, old counts, or old version references introduced by the branch delta.

## Output Expectations

When using this skill, the coding agent should produce:

1. A short branch-impact summary based on commits plus uncommitted changes.
2. A decision summary for each affected skill area:
   - update existing skill
   - add new skill
   - remove obsolete skill
   - no skill change needed
3. The actual file edits.
4. A validation summary.

## Common Pitfalls

- Looking only at committed changes and ignoring staged/unstaged work.
- Updating user skills but forgetting developer skills, or the reverse.
- Adding a new skill when an existing skill should simply be expanded.
- Forgetting eval updates after changing a user skill.
- Forgetting docs/spec inventory counts after adding or removing a developer skill.
- Describing a capability from memory instead of checking the live example/module/test files.

## Quick Heuristic

Use this branch-sync heuristic:

- **Code shape changed, workflow same** → update an existing skill.
- **New reusable workflow appeared** → add a new skill.
- **Workflow disappeared or was fully replaced** → remove or merge a skill.
- **Only one-off implementation details changed** → no new skill; at most patch wording/examples.