# Sprint rollover: "Start new iteration"

The **Start new iteration** workflow ([`workflows/start-new-iteration.yaml`](workflows/start-new-iteration.yaml))
does for the [Agent Kernel project board](https://github.com/orgs/yaalalabs/projects/3) what Jira's
"Complete sprint" does. In one run it:

1. creates the new iteration on the board's **Iteration** field, or uses it if an iteration with that
   name already exists;
2. moves every `yaalalabs/agent-kernel` issue and draft item in the previous iteration that is not
   `Done` or `Canceled` into the new iteration. Only the Iteration field changes; Status and everything
   else stay as they are;
3. closes every open `yaalalabs/agent-kernel` issue on the board whose Status is `Done` (reason
   *completed*) or `Canceled` (reason *not planned*);
4. puts back any Status that the board's "Item closed" automation changed when step 3 closed the issue
   (see [Status restore after closing](#status-restore-after-closing)).

**Contents:** [Why it exists](#why-it-exists) · [Running it](#running-it) ·
[How a run works](#how-a-run-works) · [Which items it touches](#which-items-it-touches) ·
[Creating the iteration](#creating-the-iteration) · [Closing issues](#closing-done-and-canceled-issues) ·
[Status restore](#status-restore-after-closing) · [Job summary](#job-summary) · [Errors](#errors) ·
[Re-running](#re-running-and-recovery) · [Design decisions](#design-decisions-and-non-goals) ·
[Implementation](#implementation) · [Configuration](#configuration) ·
[Prerequisite](#prerequisite-github-app-permissions) · [Local development](#local-development) ·
[Troubleshooting](#troubleshooting)

## Why it exists

- **GitHub Projects has no "complete sprint".** Adding an iteration (in the UI or via the API) only
  creates a date range. Items in the previous iteration keep pointing at it, so unfinished work drops
  out of the "current iteration" views instead of carrying over, as it does in Jira.
- **Moving items by hand does not scale.** At every sprint boundary someone had to find and re-assign
  each unfinished item, which is slow and easy to get wrong (missed items, wrong iteration picked).
- **`Canceled` issues were never closed.** The board's built-in "Auto-close issue" automation can
  react to only one Status value (in effect `Done`), so issues moved to `Canceled` stayed open.
- **The API supports everything needed.** Verified by schema introspection on 2026-10-04:
  - `updateProjectV2Field(iterationConfiguration)` replaces the Iteration field's iterations. Passing
    each existing iteration's `id` keeps its identity, so items already assigned to it keep it.
  - `updateProjectV2ItemFieldValue` sets an item's Iteration or Status.
  - `closeIssue(stateReason)` closes an issue as *completed* or *not planned*.

## Running it

Actions tab → **Start new iteration** → **Run workflow**. It runs only when dispatched; there is no
schedule.

| Input | Required | Notes |
| --- | --- | --- |
| `previous_iteration` | yes | Name of the iteration whose unfinished items move, e.g. `AK Sprint 13`. Must match an existing iteration exactly. |
| `new_iteration` | yes | Name of the new iteration, e.g. `AK Sprint 14`. If an iteration with this name already exists, it is used as is (dates are not applied). Otherwise it is created and must match `AK Sprint <n>`. |
| `start_date` | yes | `YYYY-MM-DD`, first day of the new sprint. The sprint starts at 00:00. |
| `end_date` | yes | `YYYY-MM-DD`, last day of the new sprint, inclusive. The sprint ends at 23:59, so a 14-day sprint is Monday `start_date` to Sunday `end_date` two weeks later. |
| `dry_run` | no | Default `false`. Validates and prints the full plan, then stops. Nothing is changed. |

**Recommended:** dispatch with `dry_run: true` first, check the job summary, then dispatch again with
the same inputs and `dry_run: false`.

Example for the sprint after `AK Sprint 13` (2026-09-21..2026-10-03):

```
previous_iteration: AK Sprint 13
new_iteration:      AK Sprint 14
start_date:         2026-10-05
end_date:           2026-10-18
```

Notes on the inputs:

- Leading and trailing spaces are stripped from every input.
- Either date may be in the past or the future, and a one-day sprint (`end_date == start_date`) is
  allowed.
- GitHub stores iterations as a start day plus a duration in whole days, so the 00:00 and 23:59 times
  are implied, not stored. The duration sent is `end_date - start_date + 1` days.
- `previous_iteration` is a text field, not a dropdown: a `type: choice` input's options are fixed in
  the workflow YAML, so they cannot list the board's iterations at dispatch time.
- **"Run workflow" only appears once the workflow file is on the default branch (`develop`).** It
  cannot be dispatched from a feature branch before merge.

## How a run works

The workflow job runs these steps on `ubuntu-latest`:

1. **Checkout** the repository (the only use of the default `GITHUB_TOKEN`).
2. **Set up Python 3.12.**
3. **Run the unit tests** (`.github/scripts/tests/test_start_new_iteration.py`). If any test fails,
   the job stops here and the board is never touched.
4. **Mint a GitHub App token** from the org's `agent-kernel-ci` App, scoped to `yaalalabs/agent-kernel`
   (see [Prerequisite](#prerequisite-github-app-permissions)).
5. **Run [`scripts/start_new_iteration.py`](scripts/start_new_iteration.py)** with the inputs passed as
   environment variables and turned into CLI arguments.

The script then works in two phases. **Everything that can fail on bad input is checked before the
first write**, so a validation error never leaves the board half-changed.

### Phase 1: read and validate (no writes, same for a dry run)

In this order; the first failure stops the run:

1. Read the board settings from the workflow `env` (see [Configuration](#configuration)) and the token
   from `GH_TOKEN`.
2. Parse `start_date` and `end_date` (`YYYY-MM-DD`, real dates, `end_date >= start_date`).
3. Load the project: its id, the `Iteration` field (all current, upcoming **and completed**
   iterations, plus the field's default duration) and the `Status` field with its options. Fail if
   either field or the `Done`/`Canceled` options are missing, listing what was found.
4. Plan the iteration:
   1. fail if two iterations share a name;
   2. fail if `new_iteration` and `previous_iteration` are the same;
   3. find `previous_iteration` by exact name, or fail;
   4. if `new_iteration` already exists, use it as is and skip the next two checks;
   5. otherwise check that `new_iteration` matches `AK Sprint <n>`;
   6. and that the new date range overlaps no existing iteration.
5. Fetch every item on the board (100 per page), with its content type, repository, issue
   number/state, Status and Iteration.
6. Select which items to move, which to skip and which issues to close (see
   [Which items it touches](#which-items-it-touches)).

A **dry run stops here** and writes the plan to the job summary, labelled `DRY RUN — no changes made`.

### Phase 2: write

1. **Create the iteration** if needed and verify the result (see
   [Creating the iteration](#creating-the-iteration)).
2. **Move items:** for each selected item, set its Iteration to the new iteration. Nothing else on the
   item changes.
3. **Close issues:** close each selected issue with the right reason (see
   [Closing issues](#closing-done-and-canceled-issues)).
4. **Restore Statuses** the "Item closed" automation changed (see
   [Status restore](#status-restore-after-closing)).
5. **Write the job summary** and exit non-zero if anything failed.

The first write error that survives the retries stops the remaining writes (see
[Re-running](#re-running-and-recovery)), with the Status restore as the one exception.

## Which items it touches

Only issues in `yaalalabs/agent-kernel` and draft items. Pull requests, issues from other repos, and
hidden ("redacted") items the token cannot read are ignored by every step: not moved, not closed, not
listed. An org project can hold items from any repo in the org; linking a repo to the board only sets
a default. Archived items are never returned by the API, so no step sees them.

Items in `previous_iteration`:

| Item | What happens |
| --- | --- |
| Open issue or draft, Status anything except `Done`/`Canceled` (including no Status) | **Moved** to the new iteration |
| Status `Done` or `Canceled` (open or closed) | **Not moved.** Stays in the sprint it finished in; an open one is closed by the closing step |
| Closed issue whose Status is not `Done`/`Canceled` | **Skipped and reported.** Its Status is inconsistent, so a person has to fix it |

Items **not** in `previous_iteration` (backlog items with no iteration, and items in any other
iteration, including older sprints) are never moved. They are still considered by the closing step.

Items move when the workflow runs, not on `start_date`. If you run it before the previous sprint ends,
anything finished after the run counts as `Done` in the new sprint.

## Creating the iteration

Only when no iteration named `new_iteration` exists.

**Why it is careful:** `updateProjectV2Field` does not add an iteration; it **replaces** the whole
iteration configuration with whatever is sent. Sending only the new iteration would delete every other
sprint and unassign their items.

**How:**

1. Take every existing iteration (current, upcoming and completed), add the new one, sort by start
   date, and send them all. Each existing one is sent with its own `id`, `title`, `startDate` and
   `duration`, unchanged; the `id` is what keeps its identity, so its items stay assigned to it.
2. The mutation also needs field-level `startDate` and `duration` (the board's defaults for the next
   iteration added in the UI). They are set to the new start date and the field's existing default
   duration.
3. Re-read the field and check that every pre-existing iteration still exists with the same dates, and
   that an iteration with the new title and dates now exists. If not, the run fails before moving
   anything (`existing iterations changed or disappeared after the update: …` or
   `iteration "<name>" (<range>) not found after the update`).

**Rules for a new iteration:**

- **Name:** must match `AK Sprint <n>`, where `<n>` is a number with no leading zeros. `AK Sprint 14`
  is accepted; `Sprint 14`, `AK Sprint 14b` and `AK Sprint 014` are not. The number is not checked
  against the sequence (it does not have to be the highest existing number + 1).
- **No overlap:** the new range must not overlap **any** existing iteration, including completed ones.
  The workflow never shortens, moves or deletes existing iterations; it fails and lists every
  conflict instead. Back-to-back sprints (new start the day after the old end) and gaps between
  sprints are allowed.

**If the iteration already exists** it is matched by name only and used as is: its own dates are kept,
`start_date`/`end_date` are ignored, and the name and overlap rules do not apply. The summary says it
was used, not created. This is what makes re-runs safe.

## Closing Done and Canceled issues

The board has two built-in automations, both **enabled** (checked via `ProjectV2.workflows` on
2026-10-04):

- **Auto-close issue:** Status set to a configured value → the issue is closed. Built-in automations
  exist once each, so it can cover only one Status. The API does not show which one, but the board has
  open `Canceled` issues and no open `Done` ones, which fits `Done`.
- **Item closed:** an issue is closed (by anyone, for any reason) → its Status is set to `Done`.

So nothing closes `Canceled` issues. GitHub Actions cannot be triggered by a project item change
(`projects_v2_item` is a webhook-only event), so a workflow cannot react to "Status set to `Canceled`"
either.

**What the run does:** as its last write step it closes every **open** in-scope issue anywhere on the
board (not only in the previous sprint) whose Status is:

- `Done` → closed as *completed* (catches any the automation missed);
- `Canceled` → closed as *not planned*.

The list is collected before any issue is closed. This step is the only closing mechanism for
`Canceled`: an issue set to `Canceled` mid-sprint stays open until the next run.

## Status restore after closing

**Problem:** the "Item closed" automation sets an issue's Status to `Done` whenever it is closed,
whatever the close reason. So when the closing step closes a `Canceled` issue as *not planned*, GitHub
immediately flips its Status to `Done`, and cancelled work shows up as finished work in the sprint.
(Seen on #441, #521 and #658: closed as *not planned* on 2026-09-28, now `Done`, with no Status change by
a person.) The automation stays on because it is useful elsewhere: issues closed in the repo or by a PR
move to `Done`.

**What the workflow does:**

1. Before closing anything, it notes the Status of each issue it will close.
2. It closes the issues.
3. It waits 15 seconds (`STATUS_SETTLE_SECONDS`) so the automation has time to act.
4. It re-reads the Status of each closed issue.
5. If a Status changed (e.g. `Canceled` → `Done`), it sets it back to the noted Status. An issue whose
   Status did not change (every `Done` one) is left alone.

Every Status set back is listed in the job summary (e.g. `yaalalabs/agent-kernel#658: Done → Canceled`).

**It runs even when closing fails part-way.** If closing an issue fails, the remaining issues are not
closed, but the restore still runs for the issues already closed, and then the run fails. The issue
whose close failed is restored too, because the close may have gone through even though the call
failed (e.g. a timeout); if it is in fact still open, its Status is unchanged and nothing is set.

**One failed restore does not stop the others.** Each failed re-read or set-back is listed under
Failures and fails the run, but every other closed issue is still attempted.

**Limits:**

- A change the automation makes more than 15 seconds after the close is not caught.
- **A re-run does not fix a missed restore.** Once an issue is closed, later runs no longer select it,
  so its Status is never checked again. If the summary lists a failed restore, or a closed `Canceled`
  issue shows `Done` on the board, set its Status back to `Canceled` by hand.

## Job summary

Every run writes a summary to the job's summary page (and to the log):

- the new iteration (title, dates, length) and whether it was created, would be created (dry run),
  already existed and was used, or `creation not confirmed` (the run stopped while creating it);
- the previous iteration (title and dates);
- **Items moved** (or *to move*): a table of `repo#number` or `draft`, title and Status;
- **Skipped** items and why;
- **Issues closed** (or *to close*) with the Status and close reason;
- **Status restored after closing**, if any;
- **Failures**, if any, with a note on what to do next.

The summary always lists what was done before a failure. A dry run cannot predict Status restores,
so it never lists any.

## Errors

### Validation errors (nothing changed)

The run checks everything before it writes. Any of these fails it with nothing changed:

- `duplicate iteration names found, iteration names have to be unique: "<name>", …`: two or more
  iterations on the board share a name. Iterations are looked up by name, so names must be unique.
  Rename them on the board first;
- `Entered previous iteration "<name>" not found`: no iteration has that exact name (case and spaces
  matter);
- `new_iteration and previous_iteration are both "<name>"`;
- `<start_date|end_date> is required`, `… is not a YYYY-MM-DD date`, `… is not a valid date`, or
  `end_date <date> is before start_date <date>`;
- when creating the new iteration:
  - `new_iteration "<name>" does not match format "AK Sprint {n}"`;
  - **overlap**: the new range overlaps any existing iteration, including completed ones. Every
    conflict is listed, for example:
    ```
    New iteration 2026-10-01..2026-10-14 overlaps "AK Sprint 13" (2026-09-21..2026-10-03)
    ```
    Pick dates after the last sprint, or edit the old sprint by hand first;
- the `Iteration`/`Status` fields, or the `Done`/`Canceled` options, missing from the board. The error
  lists what was found;
- `project yaalalabs/3 not found or not readable with this token`: usually a missing App permission;
- `missing environment variables: …` or `GH_TOKEN is not set`: a broken workflow file.

### API errors

- **Temporary errors are retried** and don't stop the run: network errors, timeouts, truncated or
  non-JSON responses, HTTP 429/500/502/503/504, a 403 that is a rate limit (`Retry-After`,
  `X-RateLimit-Remaining: 0`, or "rate limit" in the body), and GraphQL `RATE_LIMITED` errors. Up to
  5 attempts in total. The wait is `Retry-After` if given, else until `X-RateLimit-Reset` when the
  limit is used up, else 10 s, 20 s, 40 s, 60 s.
- **Any other error stops the run at that point**: a permission 403, any other GraphQL error, an
  unexpected response shape, or a temporary error still failing after 5 attempts. The steps after it
  are not attempted, the summary lists what was done and the error, and the run fails. For an
  unexpected error the Python traceback is also printed to the log.
- The two exceptions are in the Status restore: it still runs when closing stops, and one failed
  restore does not stop the others.

## Re-running and recovery

If the `new_iteration` name already exists, the run uses that iteration instead of creating it. So when
a run fails part-way (some items not moved, or an issue not closed), use **Re-run jobs** on the failed
run (it keeps the original inputs) or dispatch again with the same inputs. The second run does only the
work that is left, because every write step is safe to repeat:

| Step | Why repeating it is safe |
| --- | --- |
| Create iteration | Found by name and reused |
| Move items | Moved items are no longer in the previous iteration |
| Close issues | Closed issues are no longer selected |
| Status restore | **Not repeated**: closed issues are never selected again, so fix a failed restore by hand |

Two runs never interleave: the workflow uses `concurrency: start-new-iteration` with
`cancel-in-progress: false`, so a second dispatch waits for the first to finish.

## Design decisions and non-goals

**Decided:**

- **Manual trigger only.** No schedule for now. A fortnightly cron (weekly cron plus an even-week check)
  can be added later without changing the script.
- **The previous iteration is an input,** not worked out from dates, so the person running it decides
  exactly which sprint is being closed.
- **Any sprint length of 1 day or more** is allowed.
- **`new_iteration` is not checked against the sequence.** If it exists it is used as is; otherwise it
  only has to match the format.
- **Overlap fails the run** rather than editing existing iterations, so past sprint data is never
  changed by the workflow.
- **Closed issues with an inconsistent Status are reported, not guessed at.**
- **The "Item closed" automation stays on;** the run's Status restore undoes its `Canceled` → `Done`
  change on the issues the run closes. There is no automatic recovery for a failed restore.
- **Board names are configuration,** not hard-coded in the script (see [Configuration](#configuration)).

**Not done by this workflow:**

- moving items left in iterations older than the previous one (they are not moved or reported);
- pull requests, and issues outside `yaalalabs/agent-kernel`;
- pulling backlog (no-iteration) items into the sprint;
- shortening or editing existing iterations;
- closing issues in real time when their Status changes (that would need a webhook-driven App or a
  frequent cron sweep);
- sprint reports or velocity metrics.

## Implementation

| File | Role |
| --- | --- |
| [`workflows/start-new-iteration.yaml`](workflows/start-new-iteration.yaml) | Inputs, board settings (`env`), unit tests, App token, runs the script |
| [`scripts/start_new_iteration.py`](scripts/start_new_iteration.py) | All the logic; Python standard library only (`urllib`, `json`), so there is no dependency install step |
| [`scripts/tests/test_start_new_iteration.py`](scripts/tests/test_start_new_iteration.py) | `unittest` tests, run by the workflow before the script |

The script has one class per responsibility. The pure-logic classes do no I/O, so they are tested
directly; `IterationRollover` is tested against a fake client.

| Class | Responsibility |
| --- | --- |
| `SprintDates` | Parses and validates `start_date`/`end_date`; computes the duration |
| `IterationTitleFormat` | Checks a name against `AK Sprint {n}` |
| `IterationPlanner` | Duplicate-name check, previous/new iteration lookup, format and overlap checks, the full iteration payload to write (pure logic) |
| `ItemSelector` | Item scope; which items move, which are skipped, which issues to close and with what reason (pure logic) |
| `ProjectsClient` | GraphQL transport: pagination, retries, and the queries and mutations below |
| `RolloverConfig` | Board settings read from the environment |
| `IterationRollover` | Runs the steps in order and enforces the stop-on-error and restore rules |
| `RolloverReport` | Collects what was done and renders the job summary |

GraphQL operations used:

| Operation | Used for |
| --- | --- |
| `organization.projectV2.fields` | Project id, Iteration configuration (current + completed), Status options |
| `ProjectV2.items` (paginated, 100 per page) | Every item with content, Status and Iteration |
| `ProjectV2Item.fieldValueByName` | Re-reading one item's Status for the restore |
| `updateProjectV2Field` | Writing the iteration configuration with the new iteration |
| `updateProjectV2ItemFieldValue` | Moving an item (`iterationId`) and restoring a Status (`singleSelectOptionId`) |
| `closeIssue` | Closing with `stateReason: COMPLETED` or `NOT_PLANNED` |

**Security:**

- The default `GITHUB_TOKEN` gets `contents: read` only, for checkout. Every project and issue call uses
  the App token, scoped to the `agent-kernel` repository.
- Inputs reach the script through `env:` and are passed as quoted arguments, never inlined as `${{ }}`
  in the `run:` script, so an input cannot inject shell commands.

## Configuration

Board settings are workflow-level `env` constants in the workflow file, not inputs. The script checks
at start that the fields and status options exist.

| Variable | Value | Meaning |
| --- | --- | --- |
| `PROJECT_OWNER` | `yaalalabs` | Org that owns the board |
| `PROJECT_NUMBER` | `3` | Project number |
| `PROJECT_REPOSITORY` | `yaalalabs/agent-kernel` | The only repo whose issues are in scope |
| `ITERATION_FIELD` | `Iteration` | Iteration field name |
| `STATUS_FIELD` | `Status` | Single-select Status field name |
| `DONE_STATUS` | `Done` | Status meaning finished (closed as *completed*) |
| `CANCELED_STATUS` | `Canceled` | Status meaning dropped (closed as *not planned*) |
| `ITERATION_TITLE_FORMAT` | `AK Sprint {n}` | Name format for new iterations; `{n}` must appear exactly once |
| `STATUS_SETTLE_SECONDS` | `15` (script default) | Wait before the Status restore; optional |

## Prerequisite: GitHub App permissions

API calls use a token minted from the org's `agent-kernel-ci` GitHub App (`secrets.APP_ID` /
`secrets.APP_PRIVATE_KEY`, with `actions/create-github-app-token@v3`), because the default
`GITHUB_TOKEN` cannot write org-level Projects. The App needs:

- Organization → **Projects: Read and write** (create iterations, move items, restore Statuses);
- Repository → **Issues: Read and write** (close issues);
- to be installed on `yaalalabs/agent-kernel`.

As of 2026-10-04 the App had only `contents: write`, `metadata: read`, `pull_requests: write` and
`workflows: write`. An org owner adds the two permissions in the App settings, then accepts them on the
installation. To check:

```bash
gh api /apps/agent-kernel-ci --jq .permissions   # expect organization_projects: write, issues: write
```

## Local development

```bash
# Unit tests (the workflow runs these before the script)
python3 -m unittest discover -s .github/scripts/tests

# Dry run against the real board with your own token (needs the read:project scope:
# gh auth refresh -s read:project)
GH_TOKEN=$(gh auth token) PROJECT_OWNER=yaalalabs PROJECT_NUMBER=3 PROJECT_REPOSITORY=yaalalabs/agent-kernel \
  ITERATION_FIELD=Iteration STATUS_FIELD=Status DONE_STATUS=Done CANCELED_STATUS=Canceled \
  ITERATION_TITLE_FORMAT="AK Sprint {n}" \
  python3 .github/scripts/start_new_iteration.py --previous-iteration "AK Sprint 13" \
  --new-iteration "AK Sprint 14" --start-date 2026-10-05 --end-date 2026-10-18 --dry-run
```

Only run without `--dry-run` locally if you mean to change the real board.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| No "Run workflow" button | The workflow file is not on `develop` yet |
| `project … not found or not readable`, or an HTTP 403 that is not retried | The App lacks Projects/Issues write, or is not installed on the repo. See [Prerequisite](#prerequisite-github-app-permissions) |
| Overlap error | Choose dates after the last sprint, or fix the old sprint's dates by hand |
| `previous iteration … not found` | Check the exact name on the board, including case and spacing |
| Run failed part-way | Re-run with the same inputs |
| An item stayed in the old sprint | Its Status was `Done`/`Canceled`, it is a PR or from another repo, or it was a closed issue with an inconsistent Status (listed under Skipped) |
| A `Canceled` issue shows `Done` after a run | The restore failed or the automation acted after 15 s. Set the Status back by hand |
| A `Canceled` issue is still open | It was set to `Canceled` after the last run; the next run closes it |
