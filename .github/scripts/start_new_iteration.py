#!/usr/bin/env python3


import argparse
import json
import os
import re
import sys
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Optional


class RolloverError(Exception):
    """A validation or API failure that stops the run before (or instead of) writing."""


# Data model


@dataclass(frozen=True)
class Iteration:
    """One iteration of a Projects V2 Iteration field. ``id`` is None for one not yet created."""

    id: Optional[str]
    title: str
    start: date
    duration: int

    @property
    def end(self) -> date:
        """Inclusive last day."""
        return self.start + timedelta(days=self.duration - 1)

    @property
    def range_label(self) -> str:
        return f"{self.start.isoformat()}..{self.end.isoformat()}"

    def to_input(self) -> dict:
        """The ``ProjectV2Iteration`` input object; ``id`` preserves the iteration's identity on replacement."""
        payload = {"title": self.title, "startDate": self.start.isoformat(), "duration": self.duration}
        if self.id:
            payload["id"] = self.id
        return payload


@dataclass(frozen=True)
class ProjectItem:
    """A board item with the content and field values the rollover needs."""

    id: str
    content_type: str  # "Issue", "DraftIssue", or anything else (pull request, redacted) that is out of scope
    title: str
    status: Optional[str]
    iteration: Optional[Iteration]
    content_id: Optional[str] = None
    repo: Optional[str] = None
    number: Optional[int] = None
    state: Optional[str] = None  # "OPEN" or "CLOSED" for issues; None for draft issues

    @property
    def ref(self) -> str:
        if self.repo and self.number is not None:
            return f"{self.repo}#{self.number}"
        return "draft"

    @property
    def is_closed(self) -> bool:
        return self.state == "CLOSED"


# Pure logic


@dataclass(frozen=True)
class SprintDates:
    """The new sprint's inclusive date range: start_date 00:00 to end_date 23:59. Iterations are whole days."""

    start: date
    end: date

    @property
    def duration(self) -> int:
        return (self.end - self.start).days + 1

    @classmethod
    def from_inputs(cls, start_input: Optional[str], end_input: Optional[str]) -> "SprintDates":
        start = cls._parse("start_date", start_input)
        end = cls._parse("end_date", end_input)
        if end < start:
            raise RolloverError(f"end_date {end.isoformat()} is before start_date {start.isoformat()}")
        return cls(start, end)

    @staticmethod
    def _parse(name: str, value: Optional[str]) -> date:
        if not value:
            raise RolloverError(f"{name} is required")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise RolloverError(f"{name} {value!r} is not a YYYY-MM-DD date")
        try:
            return date.fromisoformat(value)
        except ValueError as e:
            raise RolloverError(f"{name} {value!r} is not a valid date: {e}") from e


class IterationTitleFormat:
    """An iteration naming format such as ``AK Sprint {n}``, where ``{n}`` is an unpadded sequence number."""

    PLACEHOLDER = "{n}"

    def __init__(self, title_format: str):
        if title_format.count(self.PLACEHOLDER) != 1:
            raise RolloverError(f"title format {title_format!r} must contain {self.PLACEHOLDER} exactly once")
        self.format = title_format
        prefix, suffix = title_format.split(self.PLACEHOLDER)
        self._pattern = re.compile(f"{re.escape(prefix)}([1-9][0-9]*){re.escape(suffix)}")

    def matches(self, title: str) -> bool:
        return self._pattern.fullmatch(title) is not None


@dataclass(frozen=True)
class IterationPlan:
    """The previous iteration, the new one, and the full field configuration to write if the new one is created."""

    previous: Iteration
    iteration: Iteration
    created: bool
    iterations_payload: list[dict] = field(default_factory=list)


class IterationPlanner:
    """Looks up the previous and new iterations by name; checks and builds the new one when it does not exist. No I/O."""

    def __init__(self, title_format: IterationTitleFormat):
        self.title_format = title_format

    def plan(self, existing: list[Iteration], previous_title: str, new_title: str, dates: SprintDates) -> IterationPlan:
        titles = [it.title for it in existing]
        duplicates = sorted({title for title in titles if titles.count(title) > 1})
        if duplicates:
            names = ", ".join(f'"{title}"' for title in duplicates)
            raise RolloverError(f"duplicate iteration names found, iteration names have to be unique: {names}")
        if previous_title == new_title:
            raise RolloverError(f'new_iteration and previous_iteration are both "{new_title}"')
        previous = self._find(existing, previous_title)
        if not previous:
            raise RolloverError(f'Entered previous iteration "{previous_title}" not found')

        # An existing new iteration is used as is, so a re-run with the same inputs only does the work that is left.
        existing_new = self._find(existing, new_title)
        if existing_new:
            return IterationPlan(previous=previous, iteration=existing_new, created=False)

        if not self.title_format.matches(new_title):
            raise RolloverError(f'new_iteration "{new_title}" does not match format "{self.title_format.format}"')
        conflicts = [it for it in existing if it.start <= dates.end and dates.start <= it.end]
        if conflicts:
            new_range = f"{dates.start.isoformat()}..{dates.end.isoformat()}"
            lines = [f'New iteration {new_range} overlaps "{it.title}" ({it.range_label})' for it in sorted(conflicts, key=lambda i: i.start)]
            raise RolloverError("\n".join(lines))

        new_iteration = Iteration(id=None, title=new_title, start=dates.start, duration=dates.duration)
        ordered = sorted([*existing, new_iteration], key=lambda it: it.start)
        return IterationPlan(previous=previous, iteration=new_iteration, created=True, iterations_payload=[it.to_input() for it in ordered])

    @staticmethod
    def _find(existing: list[Iteration], title: str) -> Optional[Iteration]:
        return next((it for it in existing if it.title == title), None)


@dataclass(frozen=True)
class SkippedItem:
    item: ProjectItem
    reason: str


@dataclass(frozen=True)
class IssueToClose:
    item: ProjectItem
    state_reason: str  # GraphQL IssueClosedStateReason: "COMPLETED" or "NOT_PLANNED"


@dataclass(frozen=True)
class Selection:
    moves: list[ProjectItem]
    skipped: list[SkippedItem]
    to_close: list[IssueToClose]


class ItemSelector:
    """Decides which items move into the new iteration, which are skipped, and which issues to close. No I/O."""

    def __init__(self, repository: str, done_status: str, canceled_status: str):
        self.repository = repository
        self.done_status = done_status
        self.canceled_status = canceled_status

    def select(self, items: list[ProjectItem], previous: Iteration) -> Selection:
        in_scope = [item for item in items if self._in_scope(item)]
        moves: list[ProjectItem] = []
        skipped: list[SkippedItem] = []
        for item in in_scope:
            if item.iteration is None or item.iteration.id != previous.id or self._is_finished(item):
                continue
            if item.is_closed:
                skipped.append(SkippedItem(item, f"issue is closed but Status is {item.status or '(none)'}"))
                continue
            moves.append(item)
        return Selection(moves=moves, skipped=skipped, to_close=self._issues_to_close(in_scope))

    def _in_scope(self, item: ProjectItem) -> bool:
        """Issues in the project repository and draft issues; pull requests, other repos and redacted items are ignored."""
        return item.content_type == "DraftIssue" or (item.content_type == "Issue" and item.repo == self.repository)

    def _is_finished(self, item: ProjectItem) -> bool:
        return item.status in (self.done_status, self.canceled_status)

    def _issues_to_close(self, items: list[ProjectItem]) -> list[IssueToClose]:
        reasons = {self.done_status: "COMPLETED", self.canceled_status: "NOT_PLANNED"}
        return [
            IssueToClose(item, reasons[item.status])
            for item in items
            if item.content_type == "Issue" and item.state == "OPEN" and item.status in reasons
        ]


# GitHub API


@dataclass
class ProjectSchema:
    """The project's ids and the two fields the rollover reads and writes."""

    project_id: str
    iteration_field_id: str
    iteration_default_duration: int
    iterations: list[Iteration]  # current, upcoming and completed
    status_field_id: str
    status_options: dict[str, str]  # option name → option id


_FIELDS_QUERY = """
query($owner: String!, $number: Int!) {
  organization(login: $owner) {
    projectV2(number: $number) {
      id
      fields(first: 100) {
        nodes {
          ... on ProjectV2FieldCommon { id name dataType }
          ... on ProjectV2SingleSelectField { options { id name } }
          ... on ProjectV2IterationField {
            configuration {
              duration
              iterations { id title startDate duration }
              completedIterations { id title startDate duration }
            }
          }
        }
      }
    }
  }
}
"""

_ITEMS_QUERY = """
query($projectId: ID!, $cursor: String, $statusField: String!, $iterationField: String!) {
  node(id: $projectId) {
    ... on ProjectV2 {
      items(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          content {
            __typename
            ... on Issue { id number title state repository { nameWithOwner } }
            ... on DraftIssue { id title }
          }
          status: fieldValueByName(name: $statusField) {
            ... on ProjectV2ItemFieldSingleSelectValue { name }
          }
          iteration: fieldValueByName(name: $iterationField) {
            ... on ProjectV2ItemFieldIterationValue { iterationId title startDate duration }
          }
        }
      }
    }
  }
}
"""

_ITEM_STATUS_QUERY = """
query($itemId: ID!, $statusField: String!) {
  node(id: $itemId) {
    ... on ProjectV2Item {
      status: fieldValueByName(name: $statusField) { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    }
  }
}
"""

_UPDATE_ITERATIONS_MUTATION = """
mutation($fieldId: ID!, $configuration: ProjectV2IterationFieldConfigurationInput!) {
  updateProjectV2Field(input: {fieldId: $fieldId, iterationConfiguration: $configuration}) { clientMutationId }
}
"""

_SET_FIELD_VALUE_MUTATION = """
mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $value: ProjectV2FieldValue!) {
  updateProjectV2ItemFieldValue(input: {projectId: $projectId, itemId: $itemId, fieldId: $fieldId, value: $value}) {
    clientMutationId
  }
}
"""

_CLOSE_ISSUE_MUTATION = """
mutation($issueId: ID!, $stateReason: IssueClosedStateReason!) {
  closeIssue(input: {issueId: $issueId, stateReason: $stateReason}) { clientMutationId }
}
"""


class ProjectsClient:
    """GraphQL transport for Projects V2, with pagination and retry on transient errors (rate limits, network, 5xx)."""

    MAX_ATTEMPTS = 5
    RETRYABLE_HTTP_CODES = (429, 500, 502, 503, 504)

    def __init__(self, token: str, api_url: str = "https://api.github.com", sleep: Callable[[float], None] = time.sleep):
        self.token = token
        self.graphql_url = f"{api_url.rstrip('/')}/graphql"
        self.sleep = sleep

    def graphql(self, query: str, variables: dict) -> dict:
        body = json.dumps({"query": query, "variables": variables}).encode()
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            request = urllib.request.Request(
                self.graphql_url,
                data=body,
                method="POST",
                headers={"Authorization": f"bearer {self.token}", "Content-Type": "application/json", "User-Agent": "start-new-iteration"},
            )
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    headers = response.headers
                    payload = json.load(response)
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")
                if self._is_retryable(e, detail) and attempt < self.MAX_ATTEMPTS:
                    self.sleep(self._retry_delay(e.headers, attempt))
                    continue
                raise RolloverError(f"GitHub API HTTP {e.code}: {detail}") from e
            except (urllib.error.URLError, OSError, ValueError) as e:
                # Connection reset, DNS failure, timeout or a truncated/non-JSON response.
                if attempt < self.MAX_ATTEMPTS:
                    self.sleep(self._retry_delay(None, attempt))
                    continue
                raise RolloverError(f"GitHub API request failed: {e}") from e
            errors = payload.get("errors")
            if errors:
                if any(err.get("type") == "RATE_LIMITED" for err in errors) and attempt < self.MAX_ATTEMPTS:
                    self.sleep(self._retry_delay(headers, attempt))
                    continue
                raise RolloverError("GitHub GraphQL error: " + "; ".join(err.get("message", str(err)) for err in errors))
            return payload["data"]
        raise RolloverError("GitHub API still failing after retries")

    @classmethod
    def _is_retryable(cls, error: urllib.error.HTTPError, detail: str) -> bool:
        """5xx and 429 are retried; a 403 only when it is a rate limit, not a missing permission."""
        if error.code in cls.RETRYABLE_HTTP_CODES:
            return True
        if error.code != 403:
            return False
        return bool(error.headers.get("Retry-After")) or error.headers.get("X-RateLimit-Remaining") == "0" or "rate limit" in detail.lower()

    @staticmethod
    def _retry_delay(headers, attempt: int, now: Callable[[], float] = time.time) -> float:
        """Retry-After if given; the rate-limit reset time when the limit is used up; otherwise exponential backoff."""
        headers = headers or {}
        retry_after = headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            return float(retry_after)
        reset = headers.get("X-RateLimit-Reset")
        if headers.get("X-RateLimit-Remaining") == "0" and reset and reset.isdigit():
            return max(0.0, float(reset) - now()) + 1
        return float(min(60, 2**attempt * 5))

    def load_project(self, owner: str, number: int, iteration_field: str, status_field: str) -> ProjectSchema:
        data = self.graphql(_FIELDS_QUERY, {"owner": owner, "number": number})
        project = (data.get("organization") or {}).get("projectV2")
        if not project:
            raise RolloverError(f"project {owner}/{number} not found or not readable with this token")
        fields = [f for f in project["fields"]["nodes"] if f]
        found = ", ".join(f"{f['name']} ({f['dataType']})" for f in fields)

        iteration = next((f for f in fields if f["name"] == iteration_field and f["dataType"] == "ITERATION"), None)
        if not iteration:
            raise RolloverError(f'iteration field "{iteration_field}" not found; fields found: {found}')
        status = next((f for f in fields if f["name"] == status_field and f["dataType"] == "SINGLE_SELECT"), None)
        if not status:
            raise RolloverError(f'single-select field "{status_field}" not found; fields found: {found}')

        config = iteration["configuration"]
        return ProjectSchema(
            project_id=project["id"],
            iteration_field_id=iteration["id"],
            iteration_default_duration=config["duration"],
            iterations=[self._iteration(i) for i in config["iterations"] + config["completedIterations"]],
            status_field_id=status["id"],
            status_options={o["name"]: o["id"] for o in status["options"]},
        )

    def fetch_items(self, project_id: str, status_field: str, iteration_field: str) -> list[ProjectItem]:
        items: list[ProjectItem] = []
        cursor = None
        while True:
            variables = {"projectId": project_id, "cursor": cursor, "statusField": status_field, "iterationField": iteration_field}
            page = self.graphql(_ITEMS_QUERY, variables)["node"]["items"]
            items.extend(self._item(node) for node in page["nodes"] if node)
            if not page["pageInfo"]["hasNextPage"]:
                return items
            cursor = page["pageInfo"]["endCursor"]

    def get_item_status(self, item_id: str, status_field: str) -> Optional[str]:
        node = self.graphql(_ITEM_STATUS_QUERY, {"itemId": item_id, "statusField": status_field})["node"]
        return (node.get("status") or {}).get("name")

    def update_iterations(self, field_id: str, start: date, default_duration: int, iterations: list[dict]) -> None:
        configuration = {"startDate": start.isoformat(), "duration": default_duration, "iterations": iterations}
        self.graphql(_UPDATE_ITERATIONS_MUTATION, {"fieldId": field_id, "configuration": configuration})

    def set_item_iteration(self, project_id: str, item_id: str, field_id: str, iteration_id: str) -> None:
        variables = {"projectId": project_id, "itemId": item_id, "fieldId": field_id, "value": {"iterationId": iteration_id}}
        self.graphql(_SET_FIELD_VALUE_MUTATION, variables)

    def set_item_status(self, project_id: str, item_id: str, field_id: str, option_id: str) -> None:
        variables = {"projectId": project_id, "itemId": item_id, "fieldId": field_id, "value": {"singleSelectOptionId": option_id}}
        self.graphql(_SET_FIELD_VALUE_MUTATION, variables)

    def close_issue(self, issue_id: str, state_reason: str) -> None:
        self.graphql(_CLOSE_ISSUE_MUTATION, {"issueId": issue_id, "stateReason": state_reason})

    @staticmethod
    def _iteration(raw: dict) -> Iteration:
        return Iteration(
            id=raw.get("id") or raw.get("iterationId"), title=raw["title"], start=date.fromisoformat(raw["startDate"]), duration=raw["duration"]
        )

    @classmethod
    def _item(cls, node: dict) -> ProjectItem:
        content = node.get("content") or {}
        repo = (content.get("repository") or {}).get("nameWithOwner")
        iteration = node.get("iteration")
        return ProjectItem(
            id=node["id"],
            content_type=content.get("__typename", "Unknown"),
            title=content.get("title", ""),
            status=(node.get("status") or {}).get("name"),
            iteration=cls._iteration(iteration) if iteration else None,
            content_id=content.get("id"),
            repo=repo,
            number=content.get("number"),
            state=content.get("state"),
        )


# Orchestration


@dataclass(frozen=True)
class RolloverConfig:
    """Board settings, supplied as workflow-level env constants."""

    owner: str
    project_number: int
    repository: str
    iteration_field: str
    status_field: str
    done_status: str
    canceled_status: str
    title_format: str
    status_settle_seconds: float = 15.0

    @classmethod
    def from_env(cls, env: dict) -> "RolloverConfig":
        required = [
            "PROJECT_OWNER",
            "PROJECT_NUMBER",
            "PROJECT_REPOSITORY",
            "ITERATION_FIELD",
            "STATUS_FIELD",
            "DONE_STATUS",
            "CANCELED_STATUS",
            "ITERATION_TITLE_FORMAT",
        ]
        missing = [name for name in required if not env.get(name)]
        if missing:
            raise RolloverError(f"missing environment variables: {', '.join(missing)}")
        return cls(
            owner=env["PROJECT_OWNER"],
            project_number=int(env["PROJECT_NUMBER"]),
            repository=env["PROJECT_REPOSITORY"],
            iteration_field=env["ITERATION_FIELD"],
            status_field=env["STATUS_FIELD"],
            done_status=env["DONE_STATUS"],
            canceled_status=env["CANCELED_STATUS"],
            title_format=env["ITERATION_TITLE_FORMAT"],
            status_settle_seconds=float(env.get("STATUS_SETTLE_SECONDS") or 15),
        )


@dataclass(frozen=True)
class SprintInputs:
    previous_iteration: str
    new_iteration: str
    start_date: Optional[str]
    end_date: Optional[str]
    dry_run: bool


@dataclass
class RolloverReport:
    """What the run did (or would do), rendered as the job summary."""

    dry_run: bool
    plan: Optional[IterationPlan] = None
    iteration_ready: bool = False  # the new iteration was created (and verified) or already existed
    moved: list[ProjectItem] = field(default_factory=list)
    skipped: list[SkippedItem] = field(default_factory=list)
    closed: list[IssueToClose] = field(default_factory=list)
    restored: list[tuple[ProjectItem, str]] = field(default_factory=list)  # (item, status it was flipped to)
    failures: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = ["# Start new iteration", ""]
        if self.dry_run:
            lines += ["> **DRY RUN — no changes made**", ""]
        if self.plan:
            it, previous = self.plan.iteration, self.plan.previous
            if self.plan.created and self.dry_run:
                action = "would be created"
            elif self.plan.created:
                action = "created" if self.iteration_ready else "creation not confirmed (see Failures)"
            else:
                action = "already exists, used as is (start_date/end_date not applied)"
            lines += [
                f"**New iteration:** **{it.title}** ({it.range_label}, {it.duration} days), {action}",
                "",
                f"**Previous iteration:** **{previous.title}** ({previous.range_label})",
                "",
            ]

        verb = "to move" if self.dry_run else "moved"
        lines += [f"## Items {verb} ({len(self.moved)})", ""]
        if self.moved:
            lines += ["| Item | Title | Status |", "| --- | --- | --- |"]
            lines += [f"| {i.ref} | {self._cell(i.title)} | {i.status or '(none)'} |" for i in self.moved]
        else:
            lines.append("None.")
        lines.append("")

        lines += [f"## Skipped ({len(self.skipped)})", ""]
        lines += [f"- {s.item.ref} {self._cell(s.item.title)}: {s.reason}" for s in self.skipped] or ["None."]
        lines.append("")

        verb = "to close" if self.dry_run else "closed"
        lines += [f"## Issues {verb} ({len(self.closed)})", ""]
        lines += [f"- {c.item.ref} {self._cell(c.item.title)} — Status {c.item.status} → {c.state_reason.lower()}" for c in self.closed] or ["None."]
        lines.append("")

        if self.restored:
            lines += [f"## Status restored after closing ({len(self.restored)})", ""]
            lines += [f"- {item.ref}: {flipped} → {item.status}" for item, flipped in self.restored]
            lines.append("")

        if self.failures:
            lines += [f"## Failures ({len(self.failures)})", ""]
            lines += [f"- {f}" for f in self.failures]
            lines += [
                "",
                "Apart from Status restores, the first error (after retries) stops the run, so the steps after it were not",
                "attempted. Re-run with the same inputs to complete the remaining work. A failed Status restore is not fixed",
                "by a re-run: set that Status back by hand.",
                "",
            ]
        return "\n".join(lines)

    @staticmethod
    def _cell(text: str) -> str:
        return text.replace("|", "\\|").replace("\n", " ")


class IterationRollover:
    """Runs the rollover steps in order. Validation failures stop before any write; a write error stops the remaining writes."""

    def __init__(self, client: ProjectsClient, config: RolloverConfig, inputs: SprintInputs, sleep: Callable[[float], None] = time.sleep):
        self.client = client
        self.config = config
        self.inputs = inputs
        self.sleep = sleep
        self.planner = IterationPlanner(IterationTitleFormat(config.title_format))
        self.selector = ItemSelector(config.repository, config.done_status, config.canceled_status)

    def run(self) -> RolloverReport:
        report = RolloverReport(dry_run=self.inputs.dry_run)
        dates = SprintDates.from_inputs(self.inputs.start_date, self.inputs.end_date)
        schema = self._load_project()
        report.plan = self.planner.plan(schema.iterations, self.inputs.previous_iteration, self.inputs.new_iteration, dates)
        items = self.client.fetch_items(schema.project_id, self.config.status_field, self.config.iteration_field)
        selection = self.selector.select(items, report.plan.previous)
        report.skipped = selection.skipped

        if self.inputs.dry_run:
            report.moved = selection.moves
            report.closed = selection.to_close
            return report

        # Writes stop at the first error that survives the client's retries; the report keeps what was done so far.
        try:
            target = self._create_iteration(schema, report.plan)
            report.iteration_ready = True
            self._move_items(schema, target, selection.moves, report)
            self._close_issues(schema, selection.to_close, report)
        except Exception as e:
            report.failures.append(_describe(e))
        return report

    def _load_project(self) -> ProjectSchema:
        schema = self.client.load_project(self.config.owner, self.config.project_number, self.config.iteration_field, self.config.status_field)
        missing = [s for s in (self.config.done_status, self.config.canceled_status) if s not in schema.status_options]
        if missing:
            found = ", ".join(schema.status_options)
            raise RolloverError(f"{self.config.status_field} options {missing} not found; options found: {found}")
        return schema

    def _create_iteration(self, schema: ProjectSchema, plan: IterationPlan) -> Iteration:
        if not plan.created:
            return plan.iteration
        self.client.update_iterations(schema.iteration_field_id, plan.iteration.start, schema.iteration_default_duration, plan.iterations_payload)
        after = self.client.load_project(self.config.owner, self.config.project_number, self.config.iteration_field, self.config.status_field)
        after_by_id = {it.id: it for it in after.iterations}
        damaged = [
            f'"{it.title}" ({it.id}, {it.range_label})'
            for it in schema.iterations
            if it.id not in after_by_id or (after_by_id[it.id].start, after_by_id[it.id].duration) != (it.start, it.duration)
        ]
        if damaged:
            raise RolloverError("existing iterations changed or disappeared after the update: " + "; ".join(damaged))
        new = plan.iteration
        existing_ids = {it.id for it in schema.iterations}
        created = next(
            (
                it
                for it in after.iterations
                if it.id not in existing_ids and (it.title, it.start, it.duration) == (new.title, new.start, new.duration)
            ),
            None,
        )
        if not created:
            raise RolloverError(f'iteration "{new.title}" ({new.range_label}) not found after the update')
        return created

    def _move_items(self, schema: ProjectSchema, target: Iteration, moves: list[ProjectItem], report: RolloverReport) -> None:
        for item in moves:
            try:
                self.client.set_item_iteration(schema.project_id, item.id, schema.iteration_field_id, target.id)
            except Exception as e:
                raise RolloverError(f"move {item.ref} ({item.title}): {_describe(e)}") from e
            report.moved.append(item)

    def _close_issues(self, schema: ProjectSchema, to_close: list[IssueToClose], report: RolloverReport) -> None:
        close_error: Optional[RolloverError] = None
        to_restore: list[IssueToClose] = []
        for entry in to_close:
            try:
                self.client.close_issue(entry.item.content_id, entry.state_reason)
            except Exception as e:
                close_error = RolloverError(f"close {entry.item.ref}: {_describe(e)}")
                # The close may have been applied even though the call failed (e.g. a timeout), so restore it too;
                # if the issue is still open its Status is unchanged and the restore does nothing.
                to_restore.append(entry)
                break
            report.closed.append(entry)
            to_restore.append(entry)
        # Restore runs even when closing stopped part-way: a re-run never selects an issue that is already closed, so
        # a skipped restore would leave it Done for good.
        self._restore_statuses(schema, to_restore, report)
        if close_error:
            raise close_error

    def _restore_statuses(self, schema: ProjectSchema, entries: list[IssueToClose], report: RolloverReport) -> None:
        """Undo the "Item closed" automation, which sets Status to Done on every close (so a Canceled issue becomes Done).

        item.status is the Status recorded before closing; wait, re-read, and set back any that changed. Every closed issue
        is attempted, since none of them is picked up again by a re-run.
        """
        if not entries:
            return
        self.sleep(self.config.status_settle_seconds)
        for entry in entries:
            item = entry.item
            try:
                current = self.client.get_item_status(item.id, self.config.status_field)
                if current != item.status:
                    self.client.set_item_status(schema.project_id, item.id, schema.status_field_id, schema.status_options[item.status])
                    report.restored.append((item, current or "(none)"))
            except Exception as e:
                report.failures.append(f"restore Status of {item.ref}: {_describe(e)}")


def _describe(error: Exception) -> str:
    """A RolloverError's own message; anything else (a bug or an unexpected response shape) with its type.

    For anything unexpected the traceback is also printed to the log, since the message alone is rarely enough to debug it.
    """
    if isinstance(error, RolloverError):
        return str(error)
    traceback.print_exception(error)
    return f"unexpected {type(error).__name__}: {error}"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Start a new project iteration and spill unfinished items into it.")
    parser.add_argument("--previous-iteration", required=True, help="name of the iteration whose unfinished items move")
    parser.add_argument("--new-iteration", required=True, help="name of the iteration to create (or use, if it already exists)")
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD, first day of the new sprint (starts 00:00)")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD, last day of the new sprint, inclusive (ends 23:59)")
    parser.add_argument("--dry-run", action="store_true", help="validate and print the plan without changing anything")
    args = parser.parse_args(argv)

    report: Optional[RolloverReport] = None
    try:
        config = RolloverConfig.from_env(dict(os.environ))
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise RolloverError("GH_TOKEN is not set")
        previous, new = args.previous_iteration.strip(), args.new_iteration.strip()
        if not previous or not new:
            raise RolloverError("previous_iteration and new_iteration are required")
        inputs = SprintInputs(previous, new, args.start_date.strip() or None, args.end_date.strip() or None, args.dry_run)
        rollover = IterationRollover(ProjectsClient(token), config, inputs)
        report = rollover.run()
    except Exception as e:
        message = _describe(e)
        for line in message.splitlines():
            print(f"::error::{line}")
        _write_summary(f"# Start new iteration\n\n**Failed:**\n\n```\n{message}\n```\n")
        return 1

    summary = report.render()
    print(summary)
    for failure in report.failures:
        print(f"::error::{failure}")
    _write_summary(summary)
    return 1 if report.failures else 0


def _write_summary(markdown: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(markdown + "\n")


if __name__ == "__main__":
    sys.exit(main())
