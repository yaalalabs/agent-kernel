---
name: ak-dev-sync-changelog-from-branch
description: >
  Write the changelog fragment(s) for an Open Agent Kernel branch before it is merged. Use this
  skill when a feature or bugfix branch is functionally ready, in the same end-of-branch pass as
  ak-dev-sync-docs-from-branch and ak-dev-sync-skills-from-branch: it reads the branch delta,
  decides whether users of OAK would notice the change, and adds changelog.d/<issue>.<type>.md
  files written for users (never an edit to CHANGELOG.md), then checks them the way the
  Changelog Check workflow will.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Sync the Changelog From Branch Changes

Use this skill near the end of a branch, before the PR is opened or finalized, to add the
changelog fragment(s) the branch needs.

`CHANGELOG.md` is built from fragment files under `changelog.d/`, one per change, so PRs never
conflict on it. The Publish workflow compiles them with towncrier (`towncrier.toml`) into a new
version section at release time and deletes them. The canonical rules are in `CONTRIBUTING.md`,
"Changelog entries"; this skill applies them to a branch.

## Rules That Never Change

- Never edit `CHANGELOG.md`. Version sections are written only by `publish.yaml`; a maintainer
  edits the file only to correct an already-released entry.
- Fragments are written for people who **use** OAK (the `agentkernel` package, the Helm chart, the
  Terraform modules, the bundled skills, the deployment templates), not for OAK's developers.
- The `auto-sync-skills-docs.yaml` follow-up PRs never add fragments; the source PR owns its entry.

## Step 1: Determine the Base and the Issue

1. Base branch: the PR target if known, else `origin/develop`. Use `git merge-base HEAD <base>`.
2. The issue number: the issue the PR fixes (`Fixes #N` in the PR body), the number in the branch
   name (`feature/664-changelog`), or the spec directory (`docs/specs/664-*/`). If there is no
   issue, the fragment is an orphan (Step 5).
3. The PR title, or the title it will have. Its Conventional Commits type decides whether the
   Changelog Check requires a fragment (Step 7).

## Step 2: Read the Branch Delta

Read the committed changes since the merge base and the staged and unstaged changes. Look for what
a user would see:

- public classes, functions, exports and import paths in `ak-py/src/agentkernel/`
- `AKConfig` fields in `ak-py/src/agentkernel/core/config.py`: added, renamed, removed, changed
  defaults; `AK_*` environment variables
- REST/A2A/MCP/AG-UI request and response fields, status codes, CLI flags
- optional-dependency extras and dependency bounds in `ak-py/pyproject.toml`
- Terraform module inputs and outputs under `ak-deployment/`, Helm chart values
- bundled user skills under `ak-py/src/agentkernel/skills/`
- spec documents: a `docs/specs/<issue>-*/spec.md` "Behavioural changes" section lists exactly
  the changes that need `breaking` or `changed` fragments

## Step 3: Decide Fragment or None

Needs a fragment, one per distinct user-visible change:

- added or removed capability, framework, provider, deployment target
- added, renamed or removed config key, API field or CLI flag; changed default
- behaviour change; bug fix a user could have hit; security fix
- dependency bound change that affects installs

Needs none: tests, CI, internal refactors with no behaviour change, docs-only changes, blog posts.

A bug that only existed on the branch (introduced and fixed before merge) needs no `fixed` entry.
Several commits that together ship one capability get one entry, not one per commit.

## Step 4: Pick the Type

| Type | Use it for |
| --- | --- |
| `breaking` | Anything that makes existing code, config or deployments stop working: removed or renamed public classes, config keys, API fields, extras, Terraform inputs; changed defaults that break existing setups |
| `added` | New capability, framework, provider, deployment target, config key, API field or CLI flag |
| `changed` | Changed behaviour or default that keeps working without changes |
| `deprecated` | Something still works but will be removed |
| `removed` | Something removed that nobody should still depend on (otherwise `breaking`) |
| `fixed` | A bug a user could have hit |
| `security` | A security fix |

When in doubt between `removed`/`changed` and `breaking`, choose `breaking`: the release then
cannot ship as a patch (`publish.yaml` refuses a patch bump while a `breaking` fragment is pending),
and a PR title with `!` must carry a `breaking` fragment.

## Step 5: Name the File

- `changelog.d/<issue>.<type>.md`, for example `changelog.d/664.added.md`.
- A second entry for the same issue and type: `changelog.d/664.added.1.md`, then `.2`. In a stack of
  PRs for one issue, check the other PRs' fragment names and take the next free counter, so two PRs
  never create the same file.
- No issue: `changelog.d/+<short-slug>.<type>.md`, rendered without a link.
- Only `.md`, only a numeric counter (`664.added.registry.md` makes towncrier fail), only the seven
  types above.

## Step 6: Write the Content

One to three sentences of Markdown:

- say what changed in the user's terms (config key, API field, CLI flag, class, deployment target),
  not how it was built
- link the docs page when there is one: `https://kernel.yaala.ai/docs/<path>` (the path under
  `docs/docs/` without `.md`, unless the page's frontmatter sets `slug` or `id`); check the page
  exists
- `breaking`: say what to change, starting "To migrate, ..."
- name the surface when it is not the Python package: "Helm chart: ...", "Terraform: ..."
- do not add the issue link; towncrier appends it
- no em dashes or en dashes as punctuation (repo writing rule)

Good:

```markdown
Defer a chat to a later time or a cron cadence with a `schedule` block on the chat request, and
list, pause or cancel schedules through `/api/v1/schedules`. See
[Scheduling](https://kernel.yaala.ai/docs/advanced/scheduling).
```

Not good: "Refactor ScheduleManager to use the new TaskStore abstraction (#629)": internal, and
repeats the link towncrier adds.

## Step 7: Check It Like CI Does

```bash
# Name validation for every pending fragment (what publish.yaml runs)
python scripts/changelog_fragments.py validate

# The Changelog Check decision for this PR
python scripts/changelog_fragments.py check-pr --title="feat: <title>" --author=<login> \
  --added changelog.d/<issue>.<type>.md

# What the next release section will look like
uvx towncrier@26.9.0 build --draft --version next
```

The Changelog Check fails a `feat`, `fix`, `perf`, `refactor`, `build` or `chore` PR with no
fragment, a `!` title without a `breaking` fragment, and any invalid fragment name. `docs`, `test`,
`ci` and `style` PRs need none. When a required-type PR genuinely changes nothing users would
notice, say so in the PR description and ask a maintainer for the `no-changelog` label; do not add
an empty or internal-facing fragment to satisfy the check.

## Output Expectations

Report back:

1. The fragment file(s) added, with type and the one-line reason for each.
2. Changes you judged not user-visible, and why.
3. Whether the PR title type requires a fragment, and whether the branch is breaking (`!` title and
   `breaking` fragment must agree).
4. The output of the three checks in Step 7.

## Common Pitfalls

- Editing `CHANGELOG.md` instead of adding a fragment.
- Writing for developers: class internals, refactor names, test changes.
- Filing a removal or rename of something public as `removed` or `changed` instead of `breaking`.
- One fragment per commit instead of one per user-visible change.
- Reusing a fragment name another open PR for the same issue already uses.
- Adding a fragment in an `auto-sync-skills-docs.yaml` follow-up PR.
- Adding the issue link by hand (it appears twice).
