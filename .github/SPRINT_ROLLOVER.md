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

Design: [`docs/specs/NNN-start-new-iteration/design.md`](../docs/specs/NNN-start-new-iteration/design.md).

## Running it

Actions tab → **Start new iteration** → **Run workflow**. It runs only when dispatched; there is no schedule.

| Input | Required | Notes |
| --- | --- | --- |
| `previous_iteration` | yes | Name of the iteration whose unfinished items move, e.g. `AK Sprint 13`. Must match an existing iteration exactly. |
| `new_iteration` | yes | Name of the new iteration, e.g. `AK Sprint 14`. If an iteration with this name already exists, it is used as is (dates are not applied). Otherwise it is created and must match `AK Sprint <n>`. |
| `start_date` | yes | `YYYY-MM-DD`, first day of the new sprint. The sprint starts at 00:00. |
| `end_date` | yes | `YYYY-MM-DD`, last day of the new sprint, inclusive. The sprint ends at 23:59, so a 14-day sprint is Monday `start_date` to Sunday `end_date` two weeks later. |
| `dry_run` | no | Default `false`. Validates and prints the full plan, then stops. Nothing is changed. |

**Recommended:** dispatch with `dry_run: true` first, check the job summary, then dispatch again with
the same inputs and `dry_run: false`.

Either date may be in the past or the future, and a one-day sprint is allowed. GitHub stores
iterations as whole days, so the 00:00 and 23:59 times are implied, not stored.

## Which items it touches

Only issues in `yaalalabs/agent-kernel` and draft items. Pull requests, issues from other repos, and
hidden items the token cannot read are ignored by every step.

- **Moved:** items in `previous_iteration` whose Status is anything but `Done` or `Canceled`, including
  items with no Status.
- **Not touched:** `Done`/`Canceled` items (they stay in the sprint they finished in), backlog items with
  no iteration, and items in any other iteration (including older sprints).
- **Skipped and reported:** a closed issue in `previous_iteration` whose Status is not `Done`/`Canceled`.
  Its Status is inconsistent, so fix it by hand.

Items move when the workflow runs, not on `start_date`. If you run it before the previous sprint ends,
anything finished after the run counts as `Done` in the new sprint.

## Status restore after closing

**Problem:** the board's built-in "Item closed" automation sets an issue's Status to `Done` whenever it
is closed, whatever the close reason. So when step 3 closes a `Canceled` issue, the board would show it
as `Done`. The automation stays on because it is useful elsewhere (issues closed in the repo or by a PR
move to `Done`).

**What the workflow does:**

1. Before closing anything, it notes the Status of each issue it will close.
2. It closes the issues.
3. It waits 15 seconds so the automation has time to act.
4. It checks the Status of each closed issue again.
5. If a Status changed (e.g. `Canceled` → `Done`), it sets it back to the noted Status.

Every Status set back is listed in the job summary (e.g. `Done → Canceled`). If setting one back fails,
it is listed as a failure and the run fails. A change the automation makes more than 15 seconds after the
close is not caught.

**A re-run does not fix a missed restore.** Once an issue is closed, later runs no longer pick it up, so
its Status is never checked again. If the summary lists a failed restore, or a closed `Canceled` issue
shows `Done` on the board, set its Status back to `Canceled` by hand.

## Errors

The run checks everything before it writes. Any of these fails it with nothing changed:

- `duplicate iteration names found, iteration names have to be unique`: two or more iterations on the
  board share a name (the duplicates are listed). Rename them on the board first;
- `Entered previous iteration "<name>" not found`: no iteration has that exact name;
- `new_iteration` and `previous_iteration` are the same name;
- a date that is not `YYYY-MM-DD`, or `end_date` before `start_date`;
- when creating the new iteration:
  - its name does not match `AK Sprint <n>`;
  - **overlap**: the new range overlaps any existing iteration, including completed ones. Every
    conflict is listed, for example:
    ```
    New iteration 2026-10-01..2026-10-14 overlaps "AK Sprint 13" (2026-09-21..2026-10-03)
    ```
    The workflow never shortens or moves existing iterations. Pick dates after the last sprint, or
    edit the old sprint by hand first;
- the `Iteration`/`Status` fields, or the `Done`/`Canceled` options, missing from the board. The error
  lists what was found.

## Re-running

If the `new_iteration` name already exists, the run uses that iteration instead of creating it. So when
a run fails part-way (some items not moved, or an issue not closed), use **Re-run jobs** on the failed
run (it keeps the original inputs) or dispatch again with the same inputs. The second run uses the
iteration the first run created and does only the work that is left.

**Which errors stop the run:**

- Temporary errors (network errors, timeouts, rate limits, GitHub 5xx responses) are retried
  automatically (5 attempts in total, with a growing wait, or until the rate limit resets) and don't
  stop the run.
- Any other error, or a temporary one that is still failing after the retries, stops the run at that
  point. The steps after it are not attempted, the job summary lists what was done and the error, and
  the run fails.
- If closing an issue fails, the issues already closed (and the one that failed, in case GitHub closed
  it anyway) still get their Status restored before the run stops, and one failed restore doesn't stop
  the others.

The one exception is a failed or missed Status restore: a re-run does not fix it (see
[Status restore after closing](#status-restore-after-closing)).

## Configuration

Board settings are workflow-level `env` constants in the workflow file, not inputs:
`PROJECT_OWNER` (`yaalalabs`), `PROJECT_NUMBER` (`3`), `PROJECT_REPOSITORY` (`yaalalabs/agent-kernel`),
`ITERATION_FIELD` (`Iteration`), `STATUS_FIELD` (`Status`), `DONE_STATUS` (`Done`),
`CANCELED_STATUS` (`Canceled`) and `ITERATION_TITLE_FORMAT` (`AK Sprint {n}`).

## Prerequisite: GitHub App permissions

API calls use a token minted from the org's `agent-kernel-ci` GitHub App (`secrets.APP_ID` /
`secrets.APP_PRIVATE_KEY`), because the default `GITHUB_TOKEN` cannot write org-level Projects. The App
needs:

- Organization → **Projects: Read and write** (create iterations, move items);
- Repository → **Issues: Read and write** (close issues);
- to be installed on `yaalalabs/agent-kernel`.

An org owner adds the permissions in the App settings, then accepts them on the installation. To check:

```bash
gh api /apps/agent-kernel-ci --jq .permissions   # expect organization_projects: write, issues: write
```

## Local development

The script, [`scripts/start_new_iteration.py`](scripts/start_new_iteration.py), uses only the standard
library.

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
