#!/usr/bin/env python3
"""
Changelog fragment checks for the PR check and the publish workflow (#664).

Fragments live in changelog.d/ and towncrier compiles them into CHANGELOG.md at release time
(towncrier.toml). This script does the checks towncrier does not do on its own:

- validate:   every fragment in changelog.d/ has a name towncrier will render. towncrier's build
              silently drops a file whose type it does not know, so the release runs this first.
- check-pr:   decides whether a pull request needs a fragment, from its title type, author,
              labels and the fragments it adds (.github/workflows/changelog-check.yaml).
- check-bump: refuses a patch release while a breaking fragment is pending (publish.yaml).

Usage:
    python scripts/changelog_fragments.py validate
    python scripts/changelog_fragments.py check-pr --title "feat: add x" --author octocat \\
        --labels "documentation,no-changelog" --added changelog.d/664.added.md
    python scripts/changelog_fragments.py check-bump --bump patch

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

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class ChangelogConfig:
    """The parts of towncrier.toml the checks need."""

    directory: str
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
        return "These fragment names would not be rendered (towncrier drops unknown types silently):\n\n" f"{listed}\n\n{self.how_to()}"


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
        touched = added_names + self._fragments(modified or [])
        invalid = [n for n in touched if Fragment.parse(n, self.config) is None]
        if invalid:
            return CheckResult(False, "invalid-fragment", self.messages.invalid(invalid))

        if author.endswith("[bot]"):
            return CheckResult(True, "bot", f"Bot-authored PR (`{author}`): no changelog fragment needed.")
        if self.SKIP_LABEL in labels:
            return CheckResult(True, "label", f"The `{self.SKIP_LABEL}` label is set: no changelog fragment needed.")

        match = self.TITLE.match(title)
        if not match:
            return CheckResult(True, "title-unparsed", "The title does not follow Conventional Commits; the PR Title Check reports that.")

        valid = [f for n in added_names if (f := Fragment.parse(n, self.config))]
        if match.group("breaking"):
            if any(f.type == self.BREAKING_TYPE for f in valid):
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
        if valid:
            listed = ", ".join(f"`{f.name}`" for f in valid)
            return CheckResult(True, "fragment-added", f"Changelog fragment added: {listed}.")
        return CheckResult(
            False,
            "missing-fragment",
            f"`{title_type}:` PRs need a changelog fragment.\n\n{self.messages.how_to()}\n\n"
            f"If this PR changes nothing a user of OAK would notice, ask a maintainer to add the `{self.SKIP_LABEL}` label.",
        )


class ReleaseGuard:
    """Release-time checks on the pending fragments."""

    BREAKING_TYPE = "breaking"

    def __init__(self, fragments: FragmentDirectory):
        self.fragments = fragments
        self.messages = Messages(fragments.config)

    def validate(self) -> CheckResult:
        invalid = self.fragments.invalid()
        if invalid:
            return CheckResult(False, "invalid-fragment", self.messages.invalid(invalid))
        return CheckResult(True, "valid", f"{len(self.fragments.names())} pending changelog fragment(s), all valid.")

    def check_bump(self, bump: str) -> CheckResult:
        breaking = self.fragments.of_type(self.BREAKING_TYPE)
        if bump == "patch" and breaking:
            listed = "\n".join(f"- `{self.fragments.config.directory}/{n}`" for n in breaking)
            return CheckResult(
                False,
                "breaking-patch",
                "A patch release cannot ship breaking changes. Pending breaking fragments:\n\n"
                f"{listed}\n\nRerun the Publish workflow with `version_bump: minor`.",
            )
        return CheckResult(True, "bump-ok", f"`{bump}` bump is allowed ({len(breaking)} breaking fragment(s) pending).")


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
        bump = sub.add_parser("check-bump", help="refuse a patch bump while a breaking fragment is pending")
        bump.add_argument("--bump", required=True, choices=["patch", "minor", "major"])
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
        fragments = FragmentDirectory(self.root, self.config)
        if args.command == "validate":
            return self._report("Changelog fragments", ReleaseGuard(fragments).validate())
        if args.command == "check-bump":
            return self._report("Changelog version bump", ReleaseGuard(fragments).check_bump(args.bump))
        labels = [label.strip() for label in args.labels.split(",") if label.strip()]
        result = PullRequestPolicy(self.config).evaluate(args.title, args.author, labels, args.added, args.modified)
        return self._report("Changelog check", result)


if __name__ == "__main__":
    sys.exit(ChangelogCLI().run(sys.argv[1:]))
