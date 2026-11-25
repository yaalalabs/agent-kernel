#!/usr/bin/env python3
"""
Changelog fragment checks for the PR check and the publish workflow (#664).

Fragments live in changelog.d/ and towncrier compiles them into CHANGELOG.md at release time
(towncrier.toml). This script does the checks towncrier does not do on its own:

- validate:   every fragment in changelog.d/ has a valid name. towncrier 26.9.0 rejects an unknown
              type or a text counter, but still accepts a non-numeric issue and any file extension,
              so the release runs this first.
- check-pr:   decides whether a pull request needs a fragment, from its title type, author,
              labels and the fragments it adds or edits (.github/workflows/changelog-check.yaml).
- check-bump: refuses a release version that would ship a pending breaking fragment without raising
              the minor version (before 1.0) or the major version (from 1.0) over the last release
              in CHANGELOG.md (publish.yaml).

Usage:
    python scripts/changelog_fragments.py validate
    python scripts/changelog_fragments.py check-pr --title "feat: add x" --author octocat \\
        --labels "documentation,no-changelog" --added changelog.d/664.added.md
    python scripts/changelog_fragments.py check-bump --version 0.11.0

Each command prints a Markdown report, appends it to $GITHUB_STEP_SUMMARY when that is set, and
exits 1 when the check fails.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class ChangelogConfig:
    """The parts of towncrier.toml the checks need."""

    directory: str
    filename: str
    types: tuple[str, ...]
    ignore: tuple[str, ...]
    orphan_prefix: str

    @classmethod
    def load(cls, path: Path) -> ChangelogConfig:
        with path.open("rb") as f:
            settings = tomllib.load(f)["tool"]["towncrier"]
        types = tuple(entry["directory"] for entry in settings["type"])
        if not types:
            raise ValueError(f"{path} declares no fragment types")
        return cls(
            directory=settings["directory"],
            filename=settings.get("filename", "NEWS.rst"),
            types=types,
            ignore=tuple(settings.get("ignore", [])),
            orphan_prefix=settings.get("orphan_prefix", "+"),
        )


@dataclass(frozen=True)
class Fragment:
    """One parsed fragment file name: <issue>.<type>[.<counter>].md or <orphan_prefix><slug>.<type>[.<counter>].md."""

    name: str
    issue: str
    type: str
    counter: int | None

    @classmethod
    def parse(cls, name: str, config: ChangelogConfig) -> Fragment | None:
        """Return the parsed fragment, or None when towncrier would reject or drop the name."""
        types = "|".join(re.escape(t) for t in config.types)
        prefix = re.escape(config.orphan_prefix)
        pattern = rf"^(?P<issue>[0-9]+|{prefix}[A-Za-z0-9_-]+)\.(?P<type>{types})(?:\.(?P<counter>[0-9]+))?\.md$"
        match = re.match(pattern, name)
        if not match:
            return None
        counter = match.group("counter")
        return cls(name=name, issue=match.group("issue"), type=match.group("type"), counter=int(counter) if counter else None)


@dataclass(frozen=True)
class Version:
    """A release version, major.minor.patch; a pre-release suffix (a1, b2) is dropped."""

    PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"^([0-9]+)\.([0-9]+)\.([0-9]+)(?:[ab][0-9]+)?$")

    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, text: str) -> Version:
        match = cls.PATTERN.match(text)
        if not match:
            raise ValueError(f"Not a release version: {text!r}")
        major, minor, patch = (int(part) for part in match.groups())
        return cls(major, minor, patch)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @staticmethod
    def breaking_step(last: Version) -> str:
        """The part a breaking change must raise after `last`: minor before 1.0, major from 1.0."""
        return "minor" if last.major == 0 else "major"

    def can_break_after(self, last: Version) -> bool:
        """Whether this version may ship breaking changes after the release `last`."""
        if self.breaking_step(last) == "minor":
            return (self.major, self.minor) > (last.major, last.minor)
        return self.major > last.major


class ChangelogFile:
    """The compiled CHANGELOG.md, read for its newest release heading."""

    # towncrier.toml title_format: "## [X.Y.Z](...) - date". Only stable releases are compiled in,
    # newest first, so the first heading is the last stable release.
    HEADING = re.compile(r"^## \[([0-9]+\.[0-9]+\.[0-9]+)\]", re.MULTILINE)

    def __init__(self, root: Path, config: ChangelogConfig):
        self.path = root / config.filename

    def latest_release(self) -> Version | None:
        if not self.path.is_file():
            return None
        match = self.HEADING.search(self.path.read_text(encoding="utf-8"))
        return Version.parse(match.group(1)) if match else None


@dataclass(frozen=True)
class CheckResult:
    """The outcome of one check: whether it passed, which rule decided it, and a Markdown report."""

    ok: bool
    rule: str
    report: str


class FragmentDirectory:
    """The fragments currently in changelog.d/."""

    def __init__(self, root: Path, config: ChangelogConfig):
        self.config = config
        self.path = root / config.directory

    def names(self) -> list[str]:
        if not self.path.is_dir():
            return []
        return sorted(p.name for p in self.path.iterdir() if p.is_file() and p.name not in self.config.ignore)

    def invalid(self) -> list[str]:
        return [name for name in self.names() if Fragment.parse(name, self.config) is None]

    def of_type(self, fragment_type: str) -> list[str]:
        return [name for name in self.names() if (f := Fragment.parse(name, self.config)) and f.type == fragment_type]


class Messages:
    """Shared Markdown snippets, so the PR check and the release checks explain fragments the same way."""

    def __init__(self, config: ChangelogConfig):
        self.config = config

    def how_to(self) -> str:
        types = ", ".join(f"`{t}`" for t in self.config.types)
        return (
            f"Add a file under `{self.config.directory}/` named `<issue>.<type>.md`, for example "
            f"`{self.config.directory}/664.added.md`, with one to three sentences on what changes for users. "
            f"Types: {types}. A second entry for the same issue and type is `<issue>.<type>.1.md`; "
            f"a PR with no issue uses `{self.config.orphan_prefix}<short-slug>.<type>.md`. "
            'Rules: CONTRIBUTING.md, "Changelog entries".'
        )

    def invalid(self, names: list[str]) -> str:
        listed = "\n".join(f"- `{self.config.directory}/{n}`" for n in names)
        return "These fragment names are not valid, so the release would refuse them:\n\n" f"{listed}\n\n{self.how_to()}"


class PullRequestPolicy:
    """Decides whether a pull request must add a changelog fragment."""

    # Same pattern as .github/workflows/pr-title-check.yaml, with the type and the "!" captured.
    TITLE = re.compile(r"^(?P<type>feat|fix|docs|style|refactor|test|chore|ci|build|perf)(\([a-z0-9][a-z0-9._/-]*\))?(?P<breaking>!)?: \S")
    REQUIRED_TYPES = frozenset({"feat", "fix", "perf", "refactor", "build", "chore"})
    SKIP_LABEL = "no-changelog"
    BREAKING_TYPE = "breaking"

    def __init__(self, config: ChangelogConfig):
        self.config = config
        self.messages = Messages(config)

    def _fragments(self, paths: list[str]) -> list[str]:
        """File names of the given paths that sit directly in the fragment directory and are not ignored."""
        names = []
        for raw in paths:
            path = Path(raw)
            if path.parent.as_posix() == self.config.directory and path.name not in self.config.ignore:
                names.append(path.name)
        return names

    def evaluate(self, title: str, author: str, labels: list[str], added: list[str], modified: list[str] | None = None) -> CheckResult:
        added_names = self._fragments(added)
        modified_names = self._fragments(modified or [])
        invalid = [n for n in added_names + modified_names if Fragment.parse(n, self.config) is None]
        if invalid:
            return CheckResult(False, "invalid-fragment", self.messages.invalid(invalid))

        if author.endswith("[bot]"):
            return CheckResult(True, "bot", f"Bot-authored PR (`{author}`): no changelog fragment needed.")
        if self.SKIP_LABEL in labels:
            return CheckResult(True, "label", f"The `{self.SKIP_LABEL}` label is set: no changelog fragment needed.")

        match = self.TITLE.match(title)
        if not match:
            return CheckResult(True, "title-unparsed", "The title does not follow Conventional Commits; the PR Title Check reports that.")

        # Every name is valid from here on: an invalid one has already failed the check.
        added_fragments = [Fragment.parse(n, self.config) for n in added_names]
        modified_fragments = [Fragment.parse(n, self.config) for n in modified_names]
        if match.group("breaking"):
            if any(f.type == self.BREAKING_TYPE for f in added_fragments):
                return CheckResult(True, "breaking-title", "Breaking title with a `breaking` fragment.")
            return CheckResult(
                False,
                "breaking-title",
                f"The title marks a breaking change (`!`), so the PR must add a `{self.BREAKING_TYPE}` fragment "
                'that says what users have to change ("To migrate, ...").\n\n' + self.messages.how_to(),
            )

        title_type = match.group("type")
        if title_type not in self.REQUIRED_TYPES:
            return CheckResult(True, "exempt-type", f"`{title_type}:` PRs need no changelog fragment.")
        if added_fragments:
            listed = ", ".join(f"`{f.name}`" for f in added_fragments)
            return CheckResult(True, "fragment-added", f"Changelog fragment added: {listed}.")
        if modified_fragments:
            # A fix to a change that is not released yet corrects its pending entry instead of adding a `fixed` one.
            listed = ", ".join(f"`{f.name}`" for f in modified_fragments)
            return CheckResult(True, "fragment-updated", f"Pending changelog fragment updated: {listed}.")
        return CheckResult(
            False,
            "missing-fragment",
            f"`{title_type}:` PRs need a changelog fragment.\n\n{self.messages.how_to()} "
            "A fix to a change that has not been released yet updates that change's pending fragment instead.\n\n"
            f"If this PR changes nothing a user of OAK would notice, ask a maintainer to add the `{self.SKIP_LABEL}` label.",
        )


class ReleaseGuard:
    """Release-time checks on the pending fragments."""

    BREAKING_TYPE = "breaking"

    def __init__(self, fragments: FragmentDirectory, changelog: ChangelogFile):
        self.fragments = fragments
        self.changelog = changelog
        self.messages = Messages(fragments.config)

    def validate(self) -> CheckResult:
        invalid = self.fragments.invalid()
        if invalid:
            return CheckResult(False, "invalid-fragment", self.messages.invalid(invalid))
        return CheckResult(True, "valid", f"{len(self.fragments.names())} pending changelog fragment(s), all valid.")

    def check_bump(self, new_version: str) -> CheckResult:
        """Check the version publish.yaml is about to release, not its `version_bump` input.

        bump_version.py ignores the input when the current version is a pre-release (a stable run
        keeps the pre-release's number), so only the resulting version says what kind of release it is.
        """
        version = Version.parse(new_version)
        breaking = self.fragments.of_type(self.BREAKING_TYPE)
        if not breaking:
            return CheckResult(True, "bump-ok", f"`{new_version}` is allowed: no breaking fragment is pending.")
        last = self.changelog.latest_release()
        if last is None:
            return CheckResult(True, "bump-ok", f"`{new_version}` is allowed: `{self.changelog.path.name}` has no earlier release.")
        if version.can_break_after(last):
            return CheckResult(True, "bump-ok", f"`{new_version}` may ship the {len(breaking)} pending breaking fragment(s) after `{last}`.")
        step = Version.breaking_step(last)
        listed = "\n".join(f"- `{self.fragments.config.directory}/{n}`" for n in breaking)
        return CheckResult(
            False,
            "breaking-bump",
            f"`{new_version}` does not raise the {step} version over the last release, `{last}`, so it cannot ship "
            f"breaking changes. Pending breaking fragments:\n\n{listed}\n\n"
            f"Rerun the Publish workflow with `version_bump: {step}`. If the version before this run was a pre-release, "
            f"a stable run keeps its number, so publish a `{step}` pre-release first.",
        )


class ChangelogCLI:
    """Command-line entry point used by the workflows."""

    def __init__(self, root: Path = REPO_ROOT):
        self.root = root
        self.config = ChangelogConfig.load(root / "towncrier.toml")

    def _parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(description="Changelog fragment checks (#664)")
        sub = parser.add_subparsers(dest="command", required=True)
        sub.add_parser("validate", help="fail when a fragment in changelog.d/ would not be rendered")
        pr = sub.add_parser("check-pr", help="decide whether a pull request needs a fragment")
        pr.add_argument("--title", required=True)
        pr.add_argument("--author", required=True)
        pr.add_argument("--labels", default="", help="comma-separated label names")
        pr.add_argument("--added", nargs="*", default=[], help="paths the PR adds or renames")
        pr.add_argument("--modified", nargs="*", default=[], help="paths the PR modifies")
        bump = sub.add_parser("check-bump", help="refuse a version that cannot ship the pending breaking fragments")
        bump.add_argument("--version", required=True, help="the version being released, e.g. 0.11.0 or 0.11.0a1")
        return parser

    def _report(self, title: str, result: CheckResult) -> int:
        status = "passed" if result.ok else "failed"
        text = f"### {title}: {status}\n\nRule: `{result.rule}`\n\n{result.report}\n"
        print(text)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        return 0 if result.ok else 1

    def run(self, argv: list[str]) -> int:
        args = self._parser().parse_args(argv)
        guard = ReleaseGuard(FragmentDirectory(self.root, self.config), ChangelogFile(self.root, self.config))
        if args.command == "validate":
            return self._report("Changelog fragments", guard.validate())
        if args.command == "check-bump":
            return self._report("Changelog version bump", guard.check_bump(args.version))
        labels = [label.strip() for label in args.labels.split(",") if label.strip()]
        result = PullRequestPolicy(self.config).evaluate(args.title, args.author, labels, args.added, args.modified)
        return self._report("Changelog check", result)


if __name__ == "__main__":
    sys.exit(ChangelogCLI().run(sys.argv[1:]))
