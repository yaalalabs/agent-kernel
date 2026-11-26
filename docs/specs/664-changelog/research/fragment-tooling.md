# Research: keeping a changelog without merge conflicts

Question: how can many concurrent PRs each add a changelog entry without conflicting on one file,
and which tool compiles the entries at release time?

Everything marked **verified** was run on 2026-11-23 in a throwaway git repo (git 2.50.1) with
`uvx towncrier@24.8.0`. Everything marked **not verified** is from general knowledge of the tool
and was not run here.

## Merge behaviour

| Setup | Result | Status |
| --- | --- | --- |
| One `CHANGELOG.md`, two branches each insert a line under the same `## [Unreleased]` / `### Added` heading | First merge clean, second merge conflicts in `CHANGELOG.md` | verified |
| Same, with `CHANGELOG.md merge=union` in `.gitattributes` | Second merge succeeds and keeps both lines | verified (local `git merge` only) |
| One file per entry in `changelog.d/` (`701.added.md`, `702.added.md`) | Both merges clean | verified |
| Two branches create the same fragment name (`664.added.md`) | add/add conflict, fixed by renaming one file | expected git behaviour, not run |
| One `CHANGELOG.md`; an auto-sync branch appends `- Fix D` under `## [Unreleased]` / `### Fixed`; meanwhile a release inserts `## [0.11.0] - ...` under `## [Unreleased]`; then the auto-sync branch merges | Merge succeeds with no conflict, and `Fix D` lands under `## [0.11.0]`, the version already released | verified (one layout; whether it conflicts depends on how close the two edits are) |

Notes on `merge=union`:

- Not verified whether GitHub's PR merge (and its "can be merged" check) applies `.gitattributes`
  merge drivers. The design does not rely on it.
- A union merge keeps both sides' lines with no conflict markers, so a line that lands under the
  wrong section, or a duplicate, goes unnoticed.

## Options

| Option | Shape | Fit for this repo | Status |
| --- | --- | --- | --- |
| **towncrier** | Python; one file per entry, type in the file name; `check`, `build --draft`, `build` | Runs through `uvx` (uv is already installed in `publish.yaml`); custom types give Keep a Changelog sections; `check` is the PR gate | verified (24.8.0), see below |
| scriv | Python; one file per entry, section headings inside the file | Similar fit; type is inside the file, so a CI check has to parse content | not verified |
| changie | Go binary; YAML fragments | Adds a non-Python binary to CI and to contributor setup | not verified |
| git-cliff / release-please | Generated from commit or PR titles | No conflicts, but quality is the PR title's quality (see below); release-please also moves releases to release PRs | not verified |
| Single file + `merge=union` | Hand-edited `## [Unreleased]` | See merge notes above | partly verified |

Why PR-title generation is not enough here, from the v0.10.0 generated notes (49 PRs):

- 10 entries are by `agent-kernel-ci[bot]`; 8 of them are `docs:` follow-ups that repeat a
  feature PR's title (for example #811, #816, #878, #939).
- Titles describe the work, not the user impact: `feat: trace eval design` (#807),
  `fix: weekly integration failures 2026 10 18` (#826), `feat: 858 secret manager consumers` (#873).
- A breaking config change appears as an ordinary line: `feat: split execution.mode into
  invocation mode and message_type` (#854). In v0.10.2 a removal appears as
  `chore: remove Azure Functions support and related configurations` (#984).

## towncrier 24.8.0: verified behaviour

Config used for the test (root `towncrier.toml`):

```toml
[tool.towncrier]
directory = "changelog.d"
filename = "CHANGELOG.md"
start_string = "<!-- towncrier release notes start -->\n"
title_format = "## [{version}](https://github.com/yaalalabs/agent-kernel/releases/tag/v{version}) - {project_date}"
issue_format = "[#{issue}](https://github.com/yaalalabs/agent-kernel/issues/{issue})"
orphan_prefix = "+"
underlines = ["", "", ""]

[[tool.towncrier.type]]
directory = "breaking"
name = "Breaking changes"
showcontent = true
# ... one block per type, rendered in declared order
```

| Behaviour | Result |
| --- | --- |
| Markdown output | `filename = "CHANGELOG.md"` renders `## [version](...) - date` and `### <Type>` headings, `- entry ([#N](...))` bullets |
| Section order | Follows the declared type order, so `Breaking changes` renders first |
| `check --compare-with develop`, branch adds no fragment | exit 1, `No new newsfragments found on this branch.` |
| `check`, branch adds valid fragments | exit 0 |
| `check`, fragment with an unknown type (`700.feature.md`) or no issue part (`added.md`) | exit 1, `Invalid news fragment name: ...` |
| `build --draft`, only an unknown-type fragment present | exit 0, renders `No significant changes.`: **the entry is dropped silently** |
| `build --draft` output streams | Rendered notes on stdout, progress lines on stderr |
| `build --yes --version X --date D` | Inserts the section under `start_string`, stages `CHANGELOG.md`, `git rm`s the consumed fragments |
| `build --yes` with no fragments | Writes the heading with `No significant changes.` |
| `build --keep` | Renders without deleting fragments |
| Second entry, same issue and type | `664.added.1.md` works (counter suffix) |
| Text suffix instead of a counter | `603.added.registry.md` next to `603.added.identity.md` fails: `ValueError: multiple files for 603.added` |
| Orphan fragment `+tidy-logs.fixed.md` | Renders with no issue link |
| Fragment extension | `701.added.txt` was accepted as an `added` entry (type is the middle part) |

### towncrier 26.9.0 (the pinned version)

Re-run on 2026-11-25 with the repo's `towncrier.toml` (seven types, `ignore = ["README.md"]`):

| Behaviour | Result |
| --- | --- |
| `build --draft` with a valid fragment and an unknown-type one (`700.feature.md`) | exit 1, `Invalid news fragment name: 700.feature.md`; unlike 24.8.0, the entry is no longer dropped silently |
| `build --draft` with `701.added.txt` | renders it as an `added` entry: any extension is still accepted |
| `build --yes` | same as 24.8.0: section under the start marker, `CHANGELOG.md` staged, consumed fragments `git rm`'d, `README.md` kept |
| Rendered output | `## [X.Y.Z](.../releases/tag/vX.Y.Z) - date`, then `### Breaking changes`, `### Added`, `### Fixed`; counter and orphan names as in 24.8.0 |

`scripts/changelog_fragments.py` stays stricter than towncrier: numeric issue or orphan only, `.md`
only, a declared type, a numeric counter.

Consequences for the design:

- `check` is a sound PR gate, including for misnamed files.
- `build` alone is not a sound release gate: a fragment that slips past the PR check (renamed after
  review, pushed directly) would vanish. The release must validate `changelog.d/` itself.
- Fragment names take a numeric counter only; concurrent PRs for one issue and type must pick
  different counters, or use the PR number as the name.

## Alternative considered: the auto doc sync as the only writer

Instead of developers adding fragments, `auto-sync-skills-docs.yaml` would write each merged PR's
fragment in its follow-up `docs:` PR. Not chosen: developers write fragments in their own PR, so
the entry is reviewed with the change and does not depend on the auto-sync running. The
measurements below informed that choice.

Measured on 2026-11-25 from `gh pr list --label auto-skill-doc-sync --state all` and
`gh run list --workflow auto-sync-skills-docs.yaml`:

| Measure | Value |
| --- | --- |
| Auto-sync PRs since 2026-07-20 | 60: 59 merged, 1 closed unmerged (#797) |
| Time from auto-sync PR creation to merge | median 0.6 h, p90 16 h, max 68.2 h |
| Most auto-sync PRs open at the same time | 2 |
| Failed runs in the last 60 | 16, all since 2026-11-18, all `You have exceeded your monthly quota` from Copilot CLI |

What this alternative would have needed:

- One file per entry even with a single writer: the auto-sync PRs overlap, and a release can land
  between an auto-sync PR's creation and its merge (see the merge table above).
- A release gate for pending auto-sync work (p90 16 h to merge), or entries slip to the next release.
- A way to re-run one merged PR after a failed run; every eligible run since 2026-11-18 left no
  output because of the quota.

## Decision

towncrier, run through `uvx` with a pinned version, with developers adding fragments in their own
PRs. It is Python like the rest of the repo tooling, needs no dependency in any `pyproject.toml`,
and its `check` and `build --draft` commands map directly to the PR gate and the release body.
