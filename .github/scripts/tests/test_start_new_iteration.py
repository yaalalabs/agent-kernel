"""Unit tests for .github/scripts/start_new_iteration.py. Run: python3 -m unittest discover -s .github/scripts/tests"""

import io
import sys
import unittest
import urllib.error
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from start_new_iteration import (  # noqa: E402
    ItemSelector,
    Iteration,
    IterationPlanner,
    IterationRollover,
    IterationTitleFormat,
    ProjectItem,
    ProjectsClient,
    ProjectSchema,
    RolloverConfig,
    RolloverError,
    SprintDates,
    SprintInputs,
)

D = date.fromisoformat


REPO = "yaalalabs/agent-kernel"


def iteration(title: str, start: str, duration: int, id_: str = None) -> Iteration:
    return Iteration(id=id_ or title.replace(" ", "-").lower(), title=title, start=D(start), duration=duration)


def item(id_: str, status=None, iteration_=None, content_type="Issue", state="OPEN", repo=REPO) -> ProjectItem:
    is_issue = content_type == "Issue"
    return ProjectItem(
        id=id_,
        content_type=content_type,
        title=f"Item {id_}",
        status=status,
        iteration=iteration_,
        content_id=f"content-{id_}",
        repo=repo if is_issue or content_type == "PullRequest" else None,
        number=100 if is_issue or content_type == "PullRequest" else None,
        state=state if is_issue or content_type == "PullRequest" else None,
    )


SPRINT_12 = iteration("AK Sprint 12", "2026-09-05", 15)
SPRINT_13 = iteration("AK Sprint 13", "2026-09-21", 13)  # ends 2026-10-03


class SprintDatesTest(unittest.TestCase):
    def test_inclusive_range_and_duration(self):
        dates = SprintDates.from_inputs("2026-10-05", "2026-10-18")
        self.assertEqual((dates.start, dates.end, dates.duration), (D("2026-10-05"), D("2026-10-18"), 14))

    def test_both_dates_required(self):
        for start, end, name in [(None, "2026-10-18", "start_date"), ("2026-10-05", "", "end_date")]:
            with self.subTest(start=start, end=end):
                with self.assertRaisesRegex(RolloverError, f"{name} is required"):
                    SprintDates.from_inputs(start, end)

    def test_bad_format_names_the_input(self):
        for start, end, name in [
            ("2026/10/05", "2026-10-18", "start_date"),
            ("2026-10-05", "5 Oct", "end_date"),
            ("2026-02-30", "2026-03-10", "start_date"),
        ]:
            with self.subTest(start=start, end=end):
                with self.assertRaisesRegex(RolloverError, name):
                    SprintDates.from_inputs(start, end)

    def test_end_before_start_fails(self):
        with self.assertRaisesRegex(RolloverError, "end_date 2026-10-01 is before start_date 2026-10-05"):
            SprintDates.from_inputs("2026-10-05", "2026-10-01")

    def test_one_day_sprint_allowed(self):
        self.assertEqual(SprintDates.from_inputs("2026-10-05", "2026-10-05").duration, 1)

    def test_past_dates_allowed(self):
        self.assertEqual(SprintDates.from_inputs("2020-01-01", "2020-01-14").duration, 14)


class IterationTitleFormatTest(unittest.TestCase):
    def test_requires_single_placeholder(self):
        with self.assertRaises(RolloverError):
            IterationTitleFormat("AK Sprint")

    def test_matches(self):
        fmt = IterationTitleFormat("AK Sprint {n}")
        self.assertTrue(fmt.matches("AK Sprint 14"))
        for title in ["Sprint 14", "AK Sprint 14b", "AK Sprint 014", "AK Sprint ", "ak sprint 3"]:
            with self.subTest(title=title):
                self.assertFalse(fmt.matches(title))


class IterationPlannerTest(unittest.TestCase):
    def setUp(self):
        self.planner = IterationPlanner(IterationTitleFormat("AK Sprint {n}"))

    def plan(self, existing, previous="AK Sprint 13", new="AK Sprint 14", start="2026-10-05", end="2026-10-18"):
        return self.planner.plan(existing, previous, new, SprintDates(D(start), D(end)))

    def test_creates_new_iteration_from_inputs(self):
        plan = self.plan([SPRINT_12, SPRINT_13])
        self.assertTrue(plan.created)
        self.assertEqual(plan.previous, SPRINT_13)
        self.assertEqual((plan.iteration.title, plan.iteration.start, plan.iteration.duration), ("AK Sprint 14", D("2026-10-05"), 14))

    def test_previous_found_by_exact_name_anywhere(self):
        upcoming = iteration("AK Sprint 20", "2027-01-04", 14)
        self.assertEqual(self.plan([SPRINT_12, SPRINT_13, upcoming], previous="AK Sprint 12").previous, SPRINT_12)
        self.assertEqual(self.plan([SPRINT_13, upcoming], previous="AK Sprint 20", start="2026-10-05").previous, upcoming)

    def test_unknown_previous_fails(self):
        for name in ["AK Sprint 99", "ak sprint 13"]:
            with self.subTest(name=name):
                with self.assertRaisesRegex(RolloverError, f'Entered previous iteration "{name}" not found'):
                    self.plan([SPRINT_13], previous=name)

    def test_same_previous_and_new_fails(self):
        with self.assertRaisesRegex(RolloverError, 'new_iteration and previous_iteration are both "AK Sprint 13"'):
            self.plan([SPRINT_13], previous="AK Sprint 13", new="AK Sprint 13")

    def test_duplicate_iteration_names_fail(self):
        duplicate = iteration("AK Sprint 12", "2026-10-19", 14, "dup12")
        with self.assertRaisesRegex(RolloverError, 'duplicate iteration names found, iteration names have to be unique: "AK Sprint 12"'):
            self.plan([SPRINT_12, SPRINT_13, duplicate])

    def test_existing_new_iteration_is_used_as_is(self):
        sprint_14 = iteration("AK Sprint 14", "2026-10-05", 14, "it14")
        # Dates that differ from the existing iteration (and would overlap Sprint 13) are not applied or checked.
        plan = self.plan([SPRINT_13, sprint_14], start="2026-09-28", end="2026-10-30")
        self.assertFalse(plan.created)
        self.assertEqual(plan.iteration, sprint_14)
        self.assertEqual(plan.iterations_payload, [])

    def test_existing_new_iteration_skips_format_check(self):
        odd = iteration("Hardening week", "2026-10-05", 7)
        self.assertFalse(self.plan([SPRINT_13, odd], new="Hardening week").created)

    def test_non_matching_new_iteration_fails_when_creating(self):
        for name in ["Sprint 14", "AK Sprint 14b", "AK Sprint 014"]:
            with self.subTest(name=name):
                with self.assertRaisesRegex(RolloverError, f'new_iteration "{name}" does not match format "AK Sprint {{n}}"'):
                    self.plan([SPRINT_13], new=name)

    def test_number_is_not_checked_against_sequence(self):
        self.assertEqual(self.plan([SPRINT_13], new="AK Sprint 20").iteration.title, "AK Sprint 20")

    def test_overlap_with_completed_current_and_upcoming_lists_all(self):
        existing = [
            SPRINT_13,
            iteration("AK Sprint 14", "2026-10-04", 7),
            iteration("AK Sprint 15", "2026-10-11", 7),
            iteration("AK Sprint 16", "2026-11-01", 7),
        ]
        with self.assertRaises(RolloverError) as ctx:
            self.plan(existing, new="AK Sprint 17", start="2026-10-01", end="2026-10-14")
        message = str(ctx.exception)
        self.assertIn('New iteration 2026-10-01..2026-10-14 overlaps "AK Sprint 13" (2026-09-21..2026-10-03)', message)
        self.assertIn('"AK Sprint 14" (2026-10-04..2026-10-10)', message)
        self.assertIn('"AK Sprint 15" (2026-10-11..2026-10-17)', message)
        self.assertNotIn("AK Sprint 16", message)

    def test_adjacent_and_gap_ranges_allowed(self):
        self.assertTrue(self.plan([SPRINT_13], start="2026-10-04", end="2026-10-17").created)
        self.assertTrue(self.plan([SPRINT_13], start="2026-10-20", end="2026-11-02").created)

    def test_payload_keeps_existing_ids_and_appends_new(self):
        sprint_12 = iteration("AK Sprint 12", "2026-09-05", 15, "id12")
        sprint_13 = iteration("AK Sprint 13", "2026-09-21", 13, "id13")
        plan = self.plan([sprint_13, sprint_12])
        self.assertEqual(
            plan.iterations_payload,
            [
                {"id": "id12", "title": "AK Sprint 12", "startDate": "2026-09-05", "duration": 15},
                {"id": "id13", "title": "AK Sprint 13", "startDate": "2026-09-21", "duration": 13},
                {"title": "AK Sprint 14", "startDate": "2026-10-05", "duration": 14},
            ],
        )


class ItemSelectorTest(unittest.TestCase):
    def setUp(self):
        self.selector = ItemSelector(REPO, "Done", "Canceled")
        self.current = iteration("AK Sprint 14", "2026-10-05", 14)

    def select(self, items):
        return self.selector.select(items, SPRINT_13)

    def test_moves_unfinished_issues_and_drafts_from_previous_iteration(self):
        items = [
            item("in-progress", "In Progress", SPRINT_13),
            item("no-status", None, SPRINT_13),
            item("backlog-status", "Backlog", SPRINT_13),
            item("draft", "To Do", SPRINT_13, content_type="DraftIssue"),
        ]
        self.assertEqual([i.id for i in self.select(items).moves], ["in-progress", "no-status", "backlog-status", "draft"])

    def test_only_the_previous_iteration_is_a_source(self):
        items = [
            item("older", "To Do", SPRINT_12),
            item("backlog", "To Do", None),
            item("current", "To Do", self.current),
            item("done", "Done", SPRINT_13),
            item("canceled", "Canceled", SPRINT_13, state="CLOSED"),
            item("done-draft", "Done", SPRINT_13, content_type="DraftIssue"),
        ]
        selection = self.select(items)
        self.assertEqual(selection.moves, [])
        self.assertEqual(selection.skipped, [])

    def test_pull_requests_other_repos_and_redacted_items_are_ignored(self):
        items = [
            item("pr", "In Review", SPRINT_13, content_type="PullRequest"),
            item("done-pr", "Done", SPRINT_13, content_type="PullRequest"),
            item("other-repo", "To Do", SPRINT_13, repo="yaalalabs/other"),
            item("other-repo-done", "Done", SPRINT_13, repo="yaalalabs/other"),
            item("redacted", "To Do", SPRINT_13, content_type="Unknown"),
        ]
        selection = self.select(items)
        self.assertEqual((selection.moves, selection.skipped, selection.to_close), ([], [], []))

    def test_skips_closed_issues_with_inconsistent_status(self):
        selection = self.select([item("closed", "In Progress", SPRINT_13, state="CLOSED"), item("closed-none", None, SPRINT_13, state="CLOSED")])
        self.assertEqual(selection.moves, [])
        self.assertEqual([s.item.id for s in selection.skipped], ["closed", "closed-none"])
        self.assertEqual(selection.skipped[0].reason, "issue is closed but Status is In Progress")

    def test_close_list_is_open_issues_in_done_or_canceled_anywhere_on_board(self):
        items = [
            item("done-open", "Done", SPRINT_13),
            item("canceled-open", "Canceled", self.current),
            item("done-backlog", "Done", None),
            item("done-older", "Done", SPRINT_12),
            item("done-closed", "Done", SPRINT_13, state="CLOSED"),
            item("done-draft", "Done", SPRINT_13, content_type="DraftIssue"),
            item("open-todo", "To Do", SPRINT_13),
        ]
        to_close = {c.item.id: c.state_reason for c in self.select(items).to_close}
        self.assertEqual(to_close, {"done-open": "COMPLETED", "canceled-open": "NOT_PLANNED", "done-backlog": "COMPLETED", "done-older": "COMPLETED"})


class FakeClient:
    """In-memory stand-in for ProjectsClient that records mutations."""

    def __init__(self, iterations, items, flip_status_to=None, fail=None, damage_iterations=False):
        self.iterations = list(iterations)
        self.items = items
        self.flip_status_to = flip_status_to
        self.fail = fail or {}  # method name -> {id: exception to raise for that item/issue id}
        self.damage_iterations = damage_iterations
        self.calls = []

    def _maybe_fail(self, method, id_):
        error = self.fail.get(method, {}).get(id_)
        if error:
            raise error

    def load_project(self, owner, number, iteration_field, status_field):
        return ProjectSchema(
            project_id="P",
            iteration_field_id="F_IT",
            iteration_default_duration=12,
            iterations=list(self.iterations),
            status_field_id="F_ST",
            status_options={"To Do": "o1", "Done": "o2", "Canceled": "o3"},
        )

    def fetch_items(self, project_id, status_field, iteration_field):
        return self.items

    def update_iterations(self, field_id, start, default_duration, iterations):
        self.calls.append(("update_iterations", iterations))
        self.iterations = [Iteration(i.get("id") or "new-id", i["title"], D(i["startDate"]), i["duration"]) for i in iterations]
        if self.damage_iterations:
            self.iterations = [it for it in self.iterations if it.id == "new-id"]

    def set_item_iteration(self, project_id, item_id, field_id, iteration_id):
        self._maybe_fail("set_item_iteration", item_id)
        self.calls.append(("set_item_iteration", item_id, iteration_id))

    def close_issue(self, issue_id, state_reason):
        self._maybe_fail("close_issue", issue_id)
        self.calls.append(("close_issue", issue_id, state_reason))

    def get_item_status(self, item_id, status_field):
        self._maybe_fail("get_item_status", item_id)
        return self.flip_status_to

    def set_item_status(self, project_id, item_id, field_id, option_id):
        self.calls.append(("set_item_status", item_id, option_id))


class IterationRolloverTest(unittest.TestCase):
    CONFIG = RolloverConfig("yaalalabs", 3, REPO, "Iteration", "Status", "Done", "Canceled", "AK Sprint {n}", status_settle_seconds=0)

    def rollover(self, client, dry_run=False, previous="AK Sprint 13", new="AK Sprint 14", start="2026-10-05", end="2026-10-18", config=None):
        inputs = SprintInputs(previous, new, start, end, dry_run)
        return IterationRollover(client, config or self.CONFIG, inputs, sleep=lambda _: None).run()

    def test_dry_run_makes_no_mutations(self):
        client = FakeClient([SPRINT_13], [item("a", "To Do", SPRINT_13), item("b", "Done", SPRINT_13)])
        report = self.rollover(client, dry_run=True)
        self.assertEqual(client.calls, [])
        self.assertEqual([i.id for i in report.moved], ["a"])
        self.assertEqual([c.item.id for c in report.closed], ["b"])
        rendered = report.render()
        self.assertIn("DRY RUN — no changes made", rendered)
        self.assertIn("**New iteration:** **AK Sprint 14** (2026-10-05..2026-10-18, 14 days), would be created", rendered)
        self.assertIn("**Previous iteration:** **AK Sprint 13** (2026-09-21..2026-10-03)", rendered)

    def test_creates_iteration_moves_and_closes(self):
        client = FakeClient([SPRINT_13], [item("a", "To Do", SPRINT_13), item("b", "Canceled", SPRINT_13)], flip_status_to="Canceled")
        report = self.rollover(client)
        self.assertEqual(client.calls[0][0], "update_iterations")
        self.assertIn(("set_item_iteration", "a", "new-id"), client.calls)
        self.assertIn(("close_issue", "content-b", "NOT_PLANNED"), client.calls)
        self.assertEqual(report.restored, [])
        self.assertEqual(report.failures, [])

    def test_restores_status_changed_by_close_automation(self):
        client = FakeClient([SPRINT_13], [item("b", "Canceled", SPRINT_13)], flip_status_to="Done")
        report = self.rollover(client)
        self.assertIn(("set_item_status", "b", "o3"), client.calls)
        self.assertEqual([(i.id, flipped) for i, flipped in report.restored], [("b", "Done")])
        self.assertIn("Done → Canceled", report.render())

    def test_existing_new_iteration_is_used_without_updating_field(self):
        sprint_14 = iteration("AK Sprint 14", "2026-10-05", 14, "it14")
        client = FakeClient([SPRINT_13, sprint_14], [item("a", "To Do", SPRINT_13)])
        report = self.rollover(client, start="2026-10-06", end="2026-10-20")
        self.assertFalse(report.plan.created)
        self.assertEqual(client.calls, [("set_item_iteration", "a", "it14")])
        self.assertIn("already exists, used as is", report.render())

    def test_move_error_stops_the_run(self):
        items = [item("a", "To Do", SPRINT_13), item("fails", "To Do", SPRINT_13), item("b", "To Do", SPRINT_13), item("c", "Done", SPRINT_13)]
        client = FakeClient([SPRINT_13], items, fail={"set_item_iteration": {"fails": RolloverError("boom")}})
        report = self.rollover(client)
        self.assertEqual([i.id for i in report.moved], ["a"])
        self.assertNotIn(("set_item_iteration", "b", "new-id"), client.calls)
        self.assertFalse(any(call[0] == "close_issue" for call in client.calls))
        self.assertEqual(len(report.failures), 1)
        self.assertIn("move yaalalabs/agent-kernel#100 (Item fails): boom", report.failures[0])
        self.assertIn("Failures (1)", report.render())

    def test_unexpected_exception_stops_the_run_and_is_reported(self):
        items = [item("fails", "To Do", SPRINT_13), item("a", "To Do", SPRINT_13)]
        client = FakeClient([SPRINT_13], items, fail={"set_item_iteration": {"fails": KeyError("data")}})
        with mock.patch("start_new_iteration.traceback.print_exception") as print_exception:
            report = self.rollover(client)
        self.assertEqual(report.moved, [])
        self.assertIn("unexpected KeyError", report.failures[0])
        print_exception.assert_called_once()

    def test_close_error_stops_closing_but_restores_issues_already_closed(self):
        items = [item("a", "Canceled", SPRINT_13), item("b", "Canceled", SPRINT_13), item("c", "Done", SPRINT_13)]
        client = FakeClient([SPRINT_13], items, flip_status_to="Done", fail={"close_issue": {"content-b": RolloverError("nope")}})
        report = self.rollover(client)
        self.assertEqual([c.item.id for c in report.closed], ["a"])
        self.assertNotIn(("close_issue", "content-c", "COMPLETED"), client.calls)
        self.assertIn(("set_item_status", "a", "o3"), client.calls)
        self.assertEqual([(i.id, flipped) for i, flipped in report.restored], [("a", "Done"), ("b", "Done")])
        self.assertEqual(report.failures, ["close yaalalabs/agent-kernel#100: nope"])

    def test_failed_close_that_left_issue_open_needs_no_restore(self):
        items = [item("a", "Canceled", SPRINT_13), item("b", "Canceled", SPRINT_13)]
        # Status unchanged on re-read: issue b is still open, so nothing is set back for it.
        client = FakeClient([SPRINT_13], items, flip_status_to="Canceled", fail={"close_issue": {"content-b": RolloverError("nope")}})
        report = self.rollover(client)
        self.assertEqual(report.restored, [])
        self.assertFalse(any(call[0] == "set_item_status" for call in client.calls))

    def test_restore_error_does_not_stop_other_restores(self):
        items = [item("a", "Canceled", SPRINT_13), item("b", "Canceled", SPRINT_13)]
        client = FakeClient([SPRINT_13], items, flip_status_to="Done", fail={"get_item_status": {"a": RolloverError("gone")}})
        report = self.rollover(client)
        self.assertEqual([i.id for i, _ in report.restored], ["b"])
        self.assertEqual(len(report.failures), 1)
        self.assertIn("restore Status of", report.failures[0])

    def test_damaged_iterations_after_update_stop_before_moves(self):
        client = FakeClient([SPRINT_12, SPRINT_13], [item("a", "To Do", SPRINT_13)], damage_iterations=True)
        report = self.rollover(client)
        self.assertEqual([call[0] for call in client.calls], ["update_iterations"])
        self.assertEqual(report.moved, [])
        self.assertIn("existing iterations changed or disappeared after the update", report.failures[0])
        self.assertIn("creation not confirmed (see Failures)", report.render())
        self.assertNotIn("days), created", report.render())

    def test_only_restore_failures_do_not_claim_the_run_stopped_early(self):
        client = FakeClient([SPRINT_13], [item("a", "Canceled", SPRINT_13)], fail={"get_item_status": {"a": RolloverError("gone")}})
        rendered = self.rollover(client).render()
        self.assertIn("days), created", rendered)
        self.assertIn("Apart from Status restores", rendered)

    def test_missing_status_option_fails_before_writes(self):
        config = RolloverConfig("yaalalabs", 3, REPO, "Iteration", "Status", "Done", "Cancelled", "AK Sprint {n}")
        client = FakeClient([SPRINT_13], [])
        with self.assertRaisesRegex(RolloverError, "Cancelled"):
            self.rollover(client, config=config)
        self.assertEqual(client.calls, [])

    def test_unknown_previous_fails_before_writes(self):
        client = FakeClient([SPRINT_13], [item("a", "To Do", SPRINT_13)])
        with self.assertRaisesRegex(RolloverError, 'Entered previous iteration "AK Sprint 12" not found'):
            self.rollover(client, previous="AK Sprint 12")
        self.assertEqual(client.calls, [])

    def test_duplicate_iteration_names_fail_before_writes(self):
        client = FakeClient([SPRINT_13, iteration("AK Sprint 13", "2026-10-05", 14, "dup13")], [item("a", "To Do", SPRINT_13)])
        with self.assertRaisesRegex(RolloverError, "duplicate iteration names found"):
            self.rollover(client)
        self.assertEqual(client.calls, [])

    def test_overlap_fails_before_writes(self):
        client = FakeClient([SPRINT_13], [item("a", "To Do", SPRINT_13)])
        with self.assertRaisesRegex(RolloverError, "overlaps"):
            self.rollover(client, start="2026-10-01", end="2026-10-14")
        self.assertEqual(client.calls, [])


class ProjectsClientTest(unittest.TestCase):
    def test_network_error_is_retried_then_raised_as_rollover_error(self):
        sleeps = []
        client = ProjectsClient("token", sleep=sleeps.append)
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection reset")) as urlopen:
            with self.assertRaisesRegex(RolloverError, "GitHub API request failed: .*connection reset"):
                client.graphql("query { viewer { login } }", {})
        self.assertEqual(urlopen.call_count, ProjectsClient.MAX_ATTEMPTS)
        self.assertEqual(len(sleeps), ProjectsClient.MAX_ATTEMPTS - 1)

    def http_error(self, code, headers=None, body=b"{}"):
        return urllib.error.HTTPError("https://api.github.com/graphql", code, "error", headers or {}, io.BytesIO(body))

    def test_permission_403_is_not_retried(self):
        client = ProjectsClient("token", sleep=lambda _: None)
        error = self.http_error(403, body=b'{"message": "Resource not accessible by integration"}')
        with mock.patch("urllib.request.urlopen", side_effect=error) as urlopen:
            with self.assertRaisesRegex(RolloverError, "HTTP 403"):
                client.graphql("query { ok }", {})
        self.assertEqual(urlopen.call_count, 1)

    def test_rate_limit_and_server_errors_are_retried(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"data": {"ok": true}}'
        sleeps = []
        client = ProjectsClient("token", sleep=sleeps.append)
        errors = [
            self.http_error(403, headers={"Retry-After": "7"}),
            self.http_error(403, body=b'{"message": "You have exceeded a secondary rate limit"}'),
            self.http_error(500),
            self.http_error(429),
        ]
        with mock.patch("urllib.request.urlopen", side_effect=[*errors, response]):
            self.assertEqual(client.graphql("query { ok }", {}), {"ok": True})
        self.assertEqual(len(sleeps), 4)
        self.assertEqual(sleeps[0], 7.0)

    def test_retry_delay_prefers_retry_after_then_rate_limit_reset_then_backoff(self):
        self.assertEqual(ProjectsClient._retry_delay({"Retry-After": "7"}, 1), 7.0)
        reset = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1100"}
        self.assertEqual(ProjectsClient._retry_delay(reset, 1, now=lambda: 1000.0), 101.0)
        self.assertEqual(ProjectsClient._retry_delay({"X-RateLimit-Remaining": "12", "X-RateLimit-Reset": "1100"}, 1), 10.0)
        self.assertEqual(ProjectsClient._retry_delay(None, 4), 60.0)

    def test_graphql_rate_limited_error_is_retried(self):
        limited, ok = mock.MagicMock(), mock.MagicMock()
        limited.__enter__.return_value.read.return_value = b'{"errors": [{"type": "RATE_LIMITED", "message": "API rate limit exceeded"}]}'
        limited.__enter__.return_value.headers = {}
        ok.__enter__.return_value.read.return_value = b'{"data": {"ok": true}}'
        sleeps = []
        client = ProjectsClient("token", sleep=sleeps.append)
        with mock.patch("urllib.request.urlopen", side_effect=[limited, ok]):
            self.assertEqual(client.graphql("query { ok }", {}), {"ok": True})
        self.assertEqual(len(sleeps), 1)

    def test_timeout_is_retried_and_can_recover(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"data": {"ok": true}}'
        client = ProjectsClient("token", sleep=lambda _: None)
        with mock.patch("urllib.request.urlopen", side_effect=[TimeoutError("timed out"), response]):
            self.assertEqual(client.graphql("query { ok }", {}), {"ok": True})


if __name__ == "__main__":
    unittest.main()
