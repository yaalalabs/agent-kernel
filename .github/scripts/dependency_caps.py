#!/usr/bin/env python3
"""Dependency version handling and security fixes for Agent Kernel (issues #659, #824).

A manifest is a ``pyproject.toml`` with a sibling ``uv.lock``.

Commands, in the order the workflow runs them:

    snapshot           save locked versions and the base commit; clear old state
    alerts             read every open Dependabot alert (needs gh + a token)
    restrict           add an upper limit to every unrestricted direct dependency
    lift               raise a limit where PyPI has a newer release beyond it
    secure             make every alerted direct dependency require its patched version
    validate           run uv lock and the checks for each manifest
    failures           print how many manifests still fail
    security-fallback  for a failing manifest: undo everything, apply security fixes only, check again
    finalize           revert every manifest that still fails (exit 3 if ak-py is one)
    unlocked           apply security fixes to manifests without a uv.lock
    npm                run npm audit fix where npm alerts exist, then build
    report             check every alert again; write the PR body and the summary

The script is deterministic. The only AI step is the failure loop in the workflow.

Run with:  uv run --no-project --with packaging python dependency_caps.py <command>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import tomllib
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import ClassVar

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

# Specifier operators that already limit a dependency from above.
UPPER_OPERATORS = {"<", "<=", "~=", "==", "==="}
# Names never capped: our own package should always follow the repo.
NEVER_CAP = {"agentkernel"}
# First version part at or above this means a date version (CalVer), e.g. 2026.10.18.
CALVER_MIN_MAJOR = 2000
COMMAND_TIMEOUT_SECONDS = 1800
EXCLUDED_DIRS = {".venv", "node_modules", "site-packages", "build", "dist", ".git"}
TEST_FILE = re.compile(r"(^|/)(tests?/|test_[^/]*\.py$|[^/]*_test\.py$)")


def read_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def parse_version(raw: str | None) -> Version | None:
    try:
        return Version(raw) if raw else None
    except InvalidVersion:
        return None


class Manifest:
    """One pyproject.toml, with its uv.lock when there is one."""

    def __init__(self, root: Path, pyproject: Path):
        self.root = root
        self.pyproject = pyproject
        self.directory = pyproject.parent
        self.lock = self.directory / "uv.lock"
        self.relative = str(pyproject.relative_to(root))
        self.relative_dir = str(self.directory.relative_to(root))

    @property
    def locked(self) -> bool:
        return self.lock.exists()

    @property
    def tier(self) -> str:
        if self.relative.startswith("ak-py/"):
            return "ak-py"
        if self.relative.startswith(("e2e/", "use-cases/")):
            return "e2e"
        return "example"

    @property
    def slug(self) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "-", self.relative).strip("-")

    @property
    def has_tests(self) -> bool:
        for path in self.directory.rglob("*"):
            relative = path.relative_to(self.directory)
            if EXCLUDED_DIRS.intersection(relative.parts):
                continue
            if TEST_FILE.search(relative.as_posix() + ("/" if path.is_dir() else "")):
                return True
        return False

    def data(self) -> dict:
        return read_toml(self.pyproject)

    def locked_versions(self) -> dict[str, str]:
        """Canonical package name -> highest locked version."""
        if not self.locked:
            return {}
        versions: dict[str, Version] = {}
        for package in read_toml(self.lock).get("package", []):
            version = parse_version(package.get("version"))
            if not package.get("name") or version is None:
                continue
            key = canonicalize_name(package["name"])
            if key not in versions or version > versions[key]:
                versions[key] = version
        return {name: str(version) for name, version in versions.items()}

    def requirement_strings(self) -> list[str]:
        """Every direct dependency string in the manifest, without duplicates."""
        data = self.data()
        found: list[str] = list(data.get("project", {}).get("dependencies", []))
        for items in data.get("project", {}).get("optional-dependencies", {}).values():
            found.extend(items)
        for items in data.get("dependency-groups", {}).values():
            found.extend(item for item in items if isinstance(item, str))
        found.extend(data.get("tool", {}).get("uv", {}).get("dev-dependencies", []))
        return list(dict.fromkeys(found))

    def skipped_names(self) -> set[str]:
        """Names that must not be capped: own project, uv sources, agentkernel."""
        data = self.data()
        names = set(NEVER_CAP)
        project_name = data.get("project", {}).get("name")
        if project_name:
            names.add(canonicalize_name(project_name))
        for source in data.get("tool", {}).get("uv", {}).get("sources", {}):
            names.add(canonicalize_name(source))
        return names

    def direct_names(self) -> set[str]:
        names = set()
        for text in self.requirement_strings():
            try:
                names.add(canonicalize_name(Requirement(text).name))
            except InvalidRequirement:
                continue
        return names


class ManifestFinder:
    """Finds manifests and orders them: ak-py first, then e2e/use-cases, then examples."""

    TIER_ORDER: ClassVar[dict[str, int]] = {"ak-py": 0, "e2e": 1, "example": 2}

    def __init__(self, root: Path, prefixes: list[str]):
        self.root = root
        self.prefixes = prefixes

    def in_scope(self, relative: str) -> bool:
        return not self.prefixes or any(relative.startswith(prefix) for prefix in self.prefixes)

    def tracked(self, pattern: str) -> list[Path]:
        if (self.root / ".git").exists():
            listed = subprocess.run(
                ["git", "ls-files", pattern], cwd=self.root, capture_output=True, text=True, check=True
            ).stdout.split()
            return [self.root / item for item in listed]
        name = pattern.lstrip("*")
        return [
            path for path in self.root.rglob(name) if not EXCLUDED_DIRS.intersection(path.relative_to(self.root).parts)
        ]

    def all(self) -> list[Manifest]:
        manifests = [Manifest(self.root, path) for path in self.tracked("*pyproject.toml")]
        manifests = [m for m in manifests if self.in_scope(m.relative)]
        return sorted(manifests, key=lambda m: (self.TIER_ORDER[m.tier], m.relative))

    def find(self) -> list[Manifest]:
        return [m for m in self.all() if m.locked]

    def unlocked(self) -> list[Manifest]:
        return [m for m in self.all() if not m.locked]

    def npm_dirs(self) -> list[str]:
        dirs = [str(path.parent.relative_to(self.root)) for path in self.tracked("*package-lock.json")]
        return [d for d in dirs if self.in_scope(d + "/")]


class SpecEditor:
    """Text rules for adding, raising and securing version limits."""

    @staticmethod
    def cap_for(version: Version) -> str:
        """Next major (>= 1.0) or next minor (0.x), written like uv does: <3.0.0 / <0.228.0."""
        if version.major == 0:
            return f"0.{version.minor + 1}.0"
        return f"{version.major + 1}.0.0"

    def restrict(self, text: str, locked: str | None) -> str | None:
        """Return the dependency string with an upper limit, or None if it stays as it is."""
        try:
            requirement = Requirement(text)
        except InvalidRequirement:
            return None
        version = parse_version(locked)
        if requirement.url or version is None:
            return None
        if any(spec.operator in UPPER_OPERATORS for spec in requirement.specifier):
            return None
        if version.major >= CALVER_MIN_MAJOR:
            return None
        body, separator, marker = text.partition(";")
        stripped = body.rstrip()
        whitespace = body[len(stripped) :]
        joiner = "," if len(requirement.specifier) else ""
        return f"{stripped}{joiner}<{self.cap_for(version)}{whitespace}{separator}{marker}"

    def lift(self, text: str, latest: str) -> str | None:
        """Raise a single '<' limit so the latest release fits, or None."""
        try:
            requirement = Requirement(text)
        except InvalidRequirement:
            return None
        latest_version = parse_version(latest)
        specs = list(requirement.specifier)
        if latest_version is None or any(spec.operator in {"~=", "==", "==="} for spec in specs):
            return None
        uppers = [spec for spec in specs if spec.operator in {"<", "<="}]
        if len(uppers) != 1 or latest_version <= Version(uppers[0].version):
            return None
        if requirement.specifier.contains(latest_version):
            return None
        body, separator, marker = text.partition(";")
        pattern = re.compile(r"<=?\s*" + re.escape(uppers[0].version))
        if not pattern.search(body):
            return None
        new_body = pattern.sub(f"<{self.cap_for(latest_version)}", body, count=1)
        return f"{new_body}{separator}{marker}"

    def secure(self, text: str, patched: str) -> str | None:
        """Make the dependency require at least the patched version, or None if it already does."""
        try:
            requirement = Requirement(text)
        except InvalidRequirement:
            return None
        target = parse_version(patched)
        if requirement.url or target is None:
            return None
        extras = f"[{','.join(sorted(requirement.extras))}]" if requirement.extras else ""
        _, separator, marker = text.partition(";")
        tail = f"; {marker.strip()}" if separator else ""
        specs = list(requirement.specifier)
        # An exact pin stays an exact pin, moved to the patched version.
        pins = [s for s in specs if s.operator in {"==", "==="} and "*" not in s.version]
        if pins:
            if all(parse_version(s.version) and parse_version(s.version) >= target for s in pins):
                return None
            return f"{requirement.name}{extras}=={target}{tail}"
        lowers, uppers, others = [], [], []
        for spec in specs:
            if spec.operator in {">=", ">"}:
                lowers.append(spec)
            elif spec.operator in {"<", "<="}:
                uppers.append(spec)
            elif spec.operator == "~=":
                # ~=1.2.10 means >=1.2.10,<1.3: split it so the floor can move and the ceiling stays.
                lowers.append(spec)
                uppers.append(SpecifierSet(f"<{self._compatible_ceiling(spec.version)}").__iter__().__next__())
            else:
                others.append(spec)
        floors_ok = bool(lowers) and all(
            parse_version(s.version) is not None and parse_version(s.version) >= target for s in lowers
        )
        ceilings_ok = all(SpecifierSet(str(s)).contains(target) for s in uppers)
        if floors_ok and ceilings_ok:
            return None
        clauses = [f">={target}"]
        kept_upper = [str(s) for s in uppers if SpecifierSet(str(s)).contains(target)]
        clauses += kept_upper[:1] or [f"<{self.cap_for(target)}"]
        clauses += [str(s) for s in others if str(s) != f"!={target}"]
        return f"{requirement.name}{extras}{','.join(clauses)}{tail}"

    @staticmethod
    def _compatible_ceiling(version: str) -> str:
        """Ceiling of ~=X.Y.Z is X.(Y+1); of ~=X.Y it is (X+1)."""
        parts = [int(p) for p in Version(version).release]
        if len(parts) < 2:
            return f"{parts[0] + 1}"
        head = parts[:-1]
        head[-1] += 1
        return ".".join(str(p) for p in head)


class PyPIClient:
    """Latest stable release of a package, cached."""

    def __init__(self):
        self.cache: dict[str, str | None] = {}

    def latest(self, name: str) -> str | None:
        key = canonicalize_name(name)
        if key not in self.cache:
            self.cache[key] = self._fetch(key)
        return self.cache[key]

    @staticmethod
    def _fetch(name: str) -> str | None:
        try:
            with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/json", timeout=30) as response:
                releases = json.load(response)["releases"]
        except (OSError, ValueError, KeyError):
            return None
        best: Version | None = None
        for raw, files in releases.items():
            version = parse_version(raw)
            if version is None or version.is_prerelease or version.is_devrelease:
                continue
            if not files or all(item.get("yanked") for item in files):
                continue
            if best is None or version > best:
                best = version
        return str(best) if best else None


class State:
    """JSON files shared between commands."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "logs").mkdir(exist_ok=True)

    def path(self, name: str) -> Path:
        return self.directory / name

    def load(self, name: str, default):
        file = self.path(name)
        return json.loads(file.read_text()) if file.exists() else default

    def save(self, name: str, value) -> None:
        self.path(name).write_text(json.dumps(value, indent=2))

    def add_changes(self, changes: list[dict]) -> None:
        self.save("changes.json", self.load("changes.json", []) + changes)


class Alerts:
    """Open Dependabot alerts, saved by the `alerts` command."""

    def __init__(self, state: State):
        self.items: list[dict] = state.load("alerts.json", [])

    def pip_for(self, manifest: Manifest) -> dict[str, str]:
        """Package -> highest patched version needed, for alerts on this manifest."""
        needed: dict[str, Version] = {}
        for alert in self.items:
            if alert["ecosystem"] != "pip" or not alert["patched"]:
                continue
            if str(Path(alert["manifest_path"]).parent) != manifest.relative_dir:
                continue
            version = parse_version(alert["patched"])
            name = canonicalize_name(alert["package"])
            if version and (name not in needed or version > needed[name]):
                needed[name] = version
        return {name: str(version) for name, version in needed.items()}

    def npm_dirs(self) -> set[str]:
        return {str(Path(a["manifest_path"]).parent) for a in self.items if a["ecosystem"] == "npm"}


class AlertFetcher:
    """Command: read every open Dependabot alert through the GitHub API."""

    def __init__(self, state: State, repo: str):
        self.state = state
        self.repo = repo

    def run(self) -> int:
        token = os.environ.get("ALERTS_TOKEN") or os.environ.get("GH_TOKEN")
        env = dict(os.environ, GH_TOKEN=token) if token else dict(os.environ)
        query = (
            ".[] | {number, package: .dependency.package.name, ecosystem: .dependency.package.ecosystem, "
            "manifest_path: .dependency.manifest_path, relationship: .dependency.relationship, "
            "severity: .security_advisory.severity, ghsa: .security_advisory.ghsa_id, "
            "patched: .security_vulnerability.first_patched_version.identifier}"
        )
        result = subprocess.run(
            ["gh", "api", "--paginate", f"repos/{self.repo}/dependabot/alerts?state=open&per_page=100", "--jq", query],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if result.returncode != 0:
            print("Cannot read Dependabot alerts. The token needs 'Dependabot alerts: Read'.")
            print(result.stderr[-2000:])
            return 1
        items = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        for item in items:
            item["ecosystem"] = "pip" if item["ecosystem"] in {"pip", "uv"} else item["ecosystem"]
        self.state.save("alerts.json", items)
        print(f"read {len(items)} open alerts")
        return 0


class PyprojectRewriter:
    """Replaces dependency strings in the file text, so comments and layout stay."""

    @staticmethod
    def previous_line_is_comment(text: str, old: str) -> bool:
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if f'"{old}"' in line or f"'{old}'" in line:
                return index > 0 and lines[index - 1].strip().startswith("#")
        return False

    @staticmethod
    def replace(text: str, old: str, new: str) -> str:
        return text.replace(f'"{old}"', f'"{new}"').replace(f"'{old}'", f"'{new}'")


class Restricter:
    """Command: add an upper limit to every unrestricted direct dependency."""

    def __init__(self, manifests: list[Manifest], state: State, packages: set[str]):
        self.manifests = manifests
        self.state = state
        self.packages = packages
        self.editor = SpecEditor()

    def run(self) -> int:
        changes = []
        for manifest in self.manifests:
            text = manifest.pyproject.read_text(encoding="utf-8")
            locked = manifest.locked_versions()
            skipped = manifest.skipped_names()
            updated = text
            for original in manifest.requirement_strings():
                try:
                    name = canonicalize_name(Requirement(original).name)
                except InvalidRequirement:
                    continue
                if name in skipped or (self.packages and name not in self.packages):
                    continue
                new = self.editor.restrict(original, locked.get(name))
                if new and new != original:
                    updated = PyprojectRewriter.replace(updated, original, new)
                    changes.append(
                        {
                            "kind": "restrict",
                            "manifest": manifest.relative,
                            "package": name,
                            "old": original,
                            "new": new,
                        }
                    )
            if updated != text:
                manifest.pyproject.write_text(updated, encoding="utf-8")
        self.state.add_changes(changes)
        print(f"restricted {len(changes)} dependencies")
        return 0


class Lifter:
    """Command: raise an upper limit when PyPI has a newer release beyond it."""

    def __init__(self, manifests: list[Manifest], state: State, packages: set[str]):
        self.manifests = manifests
        self.state = state
        self.packages = packages
        self.editor = SpecEditor()
        self.pypi = PyPIClient()

    def run(self) -> int:
        names = set()
        for manifest in self.manifests:
            names |= manifest.direct_names() - manifest.skipped_names()
        if self.packages:
            names &= self.packages
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(self.pypi.latest, sorted(names)))
        changes = []
        for manifest in self.manifests:
            text = manifest.pyproject.read_text(encoding="utf-8")
            skipped = manifest.skipped_names()
            updated = text
            for original in manifest.requirement_strings():
                try:
                    name = canonicalize_name(Requirement(original).name)
                except InvalidRequirement:
                    continue
                if name in skipped or name not in names:
                    continue
                latest = self.pypi.latest(name)
                new = self.editor.lift(original, latest) if latest else None
                if not new:
                    continue
                if PyprojectRewriter.previous_line_is_comment(text, original):
                    changes.append(
                        {
                            "kind": "lift_skipped",
                            "manifest": manifest.relative,
                            "package": name,
                            "old": original,
                            "note": "documented restriction (comment above the line)",
                        }
                    )
                    continue
                updated = PyprojectRewriter.replace(updated, original, new)
                changes.append(
                    {"kind": "lift", "manifest": manifest.relative, "package": name, "old": original, "new": new}
                )
            if updated != text:
                manifest.pyproject.write_text(updated, encoding="utf-8")
        self.state.add_changes(changes)
        print(f"lifted {sum(1 for c in changes if c['kind'] == 'lift')} limits")
        return 0


class Securer:
    """Command: every alerted direct dependency must require its patched version.

    This wins over a documented restriction: a security fix is never skipped because of a comment.
    """

    def __init__(self, manifests: list[Manifest], state: State):
        self.manifests = manifests
        self.state = state
        self.alerts = Alerts(state)
        self.editor = SpecEditor()

    def apply(self, manifest: Manifest) -> list[dict]:
        needed = self.alerts.pip_for(manifest)
        if not needed:
            return []
        text = manifest.pyproject.read_text(encoding="utf-8")
        updated, changes = text, []
        for original in manifest.requirement_strings():
            try:
                name = canonicalize_name(Requirement(original).name)
            except InvalidRequirement:
                continue
            if name not in needed or name in NEVER_CAP:
                continue
            new = self.editor.secure(original, needed[name])
            if new and new != original:
                updated = PyprojectRewriter.replace(updated, original, new)
                changes.append(
                    {"kind": "security", "manifest": manifest.relative, "package": name, "old": original, "new": new}
                )
        if updated != text:
            manifest.pyproject.write_text(updated, encoding="utf-8")
        return changes

    def run(self) -> int:
        changes = [change for manifest in self.manifests for change in self.apply(manifest)]
        self.state.add_changes(changes)
        print(f"secured {len(changes)} direct dependencies")
        return 0


class CommandRunner:
    """Runs one command, appends its output to a log file."""

    @staticmethod
    def run(command: list[str], cwd: Path, log: Path) -> int:
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"\n$ {' '.join(command)}  (in {cwd})\n")
            handle.flush()
            try:
                result = subprocess.run(
                    command,
                    cwd=cwd,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    timeout=COMMAND_TIMEOUT_SECONDS,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                handle.write("\nTIMEOUT\n")
                return 124
            return result.returncode


class Baseline:
    """A clean copy of the base commit, to tell 'we broke it' from 'it was already broken'."""

    def __init__(self, root: Path, state: State):
        self.root = root
        self.state = state
        self.lock = threading.Lock()
        self.path = state.path("baseline")

    def ensure(self) -> Path:
        with self.lock:
            if not self.path.exists():
                commit = self.state.load("snapshot-meta.json", {}).get("commit", "HEAD")
                subprocess.run(
                    ["git", "worktree", "add", "--detach", str(self.path), commit],
                    cwd=self.root,
                    check=True,
                    capture_output=True,
                )
        return self.path

    def tests_pass(self, manifest: Manifest, log: Path) -> bool:
        directory = self.ensure() / manifest.relative_dir
        if CommandRunner.run(["uv", "sync", "--frozen"], directory, log) != 0:
            return False
        return CommandRunner.run(["uv", "run", "pytest"], directory, log) == 0


class Validator:
    """Command: run uv lock and the checks for each manifest."""

    def __init__(
        self,
        manifests: list[Manifest],
        state: State,
        level: str,
        upgrade: bool,
        only_failed: bool,
        workers: int,
    ):
        self.manifests = manifests
        self.state = state
        self.level = level
        self.upgrade = upgrade
        self.only_failed = only_failed
        self.workers = workers
        self.snapshot = state.load("snapshot.json", {})
        self.lock_override: dict[str, list[str]] = {}
        self.baseline = Baseline(manifests[0].root, state) if manifests else None

    def _lock_command(self, manifest: Manifest) -> list[str]:
        if manifest.relative in self.lock_override:
            return self.lock_override[manifest.relative]
        return ["uv", "lock"] + (["--upgrade"] if self.upgrade else [])

    def _steps(self, manifest: Manifest) -> list[tuple[str, list[str], Path]]:
        steps = [("uv lock", self._lock_command(manifest), manifest.directory)]
        if self.level == "full":
            if manifest.tier == "ak-py":
                steps += [
                    ("uv sync", ["uv", "sync", "--all-extras", "--no-extra", "crewai", "--dev"], manifest.directory),
                    ("pytest", ["uv", "run", "pytest"], manifest.directory),
                    ("lint", ["make", "lint-check"], manifest.root),
                ]
            else:
                steps.append(("uv sync", ["uv", "sync", "--frozen"], manifest.directory))
                if manifest.has_tests:
                    steps.append(("pytest", ["uv", "run", "pytest"], manifest.directory))
        return steps

    def _versions_unchanged(self, manifest: Manifest) -> str | None:
        before = self.snapshot.get(manifest.relative, {})
        after = manifest.locked_versions()
        moved = [f"{name} {before[name]} -> {after.get(name)}" for name in before if after.get(name) != before[name]]
        return "locked versions moved: " + ", ".join(moved[:10]) if moved else None

    def check(self, manifest: Manifest) -> dict:
        log = self.state.path(f"logs/{manifest.slug}.log")
        log.write_text("")
        note = ""
        for label, command, cwd in self._steps(manifest):
            if CommandRunner.run(command, cwd, log) == 0:
                continue
            # A non-ak-py test failure only counts when the same tests passed before the change.
            if label == "pytest" and manifest.tier != "ak-py" and self.baseline:
                with log.open("a") as handle:
                    handle.write("\n--- tests failed; running them on the base commit ---\n")
                if not self.baseline.tests_pass(manifest, log):
                    note = "tests_failing_before"
                    continue
            return self._result(manifest, "fail", label, log)
        if self.level == "lock":
            problem = self._versions_unchanged(manifest)
            if problem:
                with log.open("a") as handle:
                    handle.write(f"\n{problem}\n")
                return self._result(manifest, "fail", "versions unchanged", log)
        return self._result(manifest, "pass", "", log, note)

    @staticmethod
    def _result(manifest: Manifest, status: str, step: str, log: Path, note: str = "") -> dict:
        tail = log.read_text().splitlines()[-40:]
        return {
            "manifest": manifest.relative,
            "status": status,
            "step": step,
            "log": str(log),
            "tail": tail,
            "note": note,
        }

    def run_on(self, targets: list[Manifest]) -> dict[str, dict]:
        results = {r["manifest"]: r for r in self.state.load("results.json", [])}
        heavy = [m for m in targets if m.tier == "ak-py"]
        light = [m for m in targets if m.tier != "ak-py"]
        for manifest in heavy:
            results[manifest.relative] = self.check(manifest)
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            for result in pool.map(self.check, light):
                results[result["manifest"]] = result
        self.state.save("results.json", list(results.values()))
        failing = [r for r in results.values() if r["status"] == "fail"]
        self.state.save("failures.json", self._failure_context(failing))
        return results

    def run(self) -> int:
        targets = self.manifests
        if self.only_failed:
            failing = {r["manifest"] for r in self.state.load("results.json", []) if r["status"] == "fail"}
            targets = [m for m in self.manifests if m.relative in failing]
        results = self.run_on(targets)
        print(f"validated {len(targets)} manifests, {sum(r['status'] == 'fail' for r in results.values())} failing")
        return 0

    def _failure_context(self, failing: list[dict]) -> list[dict]:
        changes = self.state.load("changes.json", [])
        alerts = Alerts(self.state)
        by_path = {m.relative: m for m in self.manifests}
        context = []
        for result in failing:
            manifest = by_path.get(result["manifest"])
            if manifest is None:
                continue
            before, after = self.snapshot.get(manifest.relative, {}), manifest.locked_versions()
            moved = [
                {"package": name, "old": before.get(name), "new": version}
                for name, version in after.items()
                if before.get(name) != version
            ]
            context.append(
                {
                    "manifest": manifest.relative,
                    "failed_step": result["step"],
                    "log": result["log"],
                    "error_tail": result["tail"],
                    "limit_changes": [
                        c for c in changes if c["manifest"] == manifest.relative and c["kind"] != "lift_skipped"
                    ],
                    "security_minimums": alerts.pip_for(manifest),
                    "locked_version_changes": moved[:80],
                }
            )
        return context


class SecurityFallback:
    """Command: for each failing manifest, undo all changes and apply only the security fixes."""

    def __init__(self, manifests: list[Manifest], state: State, workers: int):
        self.manifests = manifests
        self.state = state
        self.workers = workers

    def run(self) -> int:
        failing = {r["manifest"] for r in self.state.load("results.json", []) if r["status"] == "fail"}
        targets = [m for m in self.manifests if m.relative in failing]
        alerts = Alerts(self.state)
        securer = Securer(targets, self.state)
        validator = Validator(self.manifests, self.state, "full", False, False, self.workers)
        retried, changes = [], []
        for manifest in targets:
            needed = alerts.pip_for(manifest)
            if not needed:
                continue
            GitFiles.restore(manifest)
            changes += [dict(c, kind="security_only") for c in securer.apply(manifest)]
            present = set(manifest.locked_versions())
            command = ["uv", "lock"]
            for name in sorted(needed):
                if name in present:
                    command += ["--upgrade-package", name]
            validator.lock_override[manifest.relative] = command
            retried.append(manifest)
        self.state.add_changes(changes)
        if retried:
            results = validator.run_on(retried)
            for manifest in retried:
                results[manifest.relative]["note"] = "security_only"
            self.state.save("results.json", list(results.values()))
        print(f"security-only retry for {len(retried)} manifests")
        return 0


class GitFiles:
    """Undo the changes to one manifest."""

    @staticmethod
    def restore(manifest: Manifest) -> None:
        files = [str(manifest.pyproject.relative_to(manifest.root))]
        if manifest.locked:
            files.append(str(manifest.lock.relative_to(manifest.root)))
        subprocess.run(["git", "checkout", "--", *files], cwd=manifest.root, check=True)


class Finalizer:
    """Command: revert every manifest that still fails."""

    def __init__(self, manifests: list[Manifest], state: State):
        self.manifests = manifests
        self.state = state

    def run(self) -> int:
        failing = {r["manifest"] for r in self.state.load("results.json", []) if r["status"] == "fail"}
        reverted = []
        for manifest in self.manifests:
            if manifest.relative in failing:
                GitFiles.restore(manifest)
                reverted.append(manifest.relative)
        self.state.save("reverted.json", reverted)
        print(f"reverted {len(reverted)} manifests")
        return 3 if any(path.startswith("ak-py/") for path in reverted) else 0


class UnlockedFixer:
    """Command: security fixes for manifests without a uv.lock (no limits: there is no locked version)."""

    def __init__(self, manifests: list[Manifest], state: State):
        self.manifests = manifests
        self.state = state

    def run(self) -> int:
        securer = Securer(self.manifests, self.state)
        results = []
        for manifest in self.manifests:
            changes = securer.apply(manifest)
            if not changes:
                continue
            log = self.state.path(f"logs/{manifest.slug}.log")
            log.write_text("")
            command = ["uv", "pip", "compile", "pyproject.toml", "--quiet", "--output-file", os.devnull]
            if CommandRunner.run(command, manifest.directory, log) == 0:
                self.state.add_changes([dict(c, kind="security") for c in changes])
                results.append({"manifest": manifest.relative, "status": "pass"})
            else:
                GitFiles.restore(manifest)
                results.append(
                    {"manifest": manifest.relative, "status": "fail", "tail": log.read_text().splitlines()[-5:]}
                )
        self.state.save("unlocked.json", results)
        print(f"unlocked manifests fixed: {sum(r['status'] == 'pass' for r in results)} of {len(results)}")
        return 0


class NpmFixer:
    """Command: npm audit fix (never --force) where npm alerts exist, then build."""

    def __init__(self, root: Path, dirs: list[str], state: State):
        self.root = root
        self.dirs = dirs
        self.state = state

    def run(self) -> int:
        wanted = Alerts(self.state).npm_dirs()
        results = []
        for relative in self.dirs:
            if relative not in wanted:
                continue
            directory = self.root / relative
            log = self.state.path(f"logs/npm-{re.sub(r'[^A-Za-z0-9]+', '-', relative)}.log")
            log.write_text("")
            files = [f"{relative}/package.json", f"{relative}/package-lock.json"]
            if CommandRunner.run(["npm", "audit", "fix", "--no-fund"], directory, log) != 0:
                with log.open("a") as handle:
                    handle.write("\nnpm audit fix exited non-zero (some fixes may need --force; not used)\n")
            changed = (
                subprocess.run(["git", "diff", "--quiet", "--", *files], cwd=self.root, check=False).returncode != 0
            )
            status = "unchanged"
            if changed:
                scripts = json.loads((directory / "package.json").read_text()).get("scripts", {})
                ok = CommandRunner.run(["npm", "ci", "--no-fund"], directory, log) == 0
                if ok and "build" in scripts:
                    ok = CommandRunner.run(["npm", "run", "build"], directory, log) == 0
                if ok:
                    status = "fixed"
                else:
                    subprocess.run(["git", "checkout", "--", *files], cwd=self.root, check=True)
                    status = "reverted"
            remaining = self._remaining(directory)
            results.append({"dir": relative, "status": status, "remaining": remaining, "log": str(log)})
        self.state.save("npm.json", results)
        print(f"npm: {[(r['dir'], r['status']) for r in results]}")
        return 0

    @staticmethod
    def _remaining(directory: Path) -> int | None:
        result = subprocess.run(["npm", "audit", "--json"], cwd=directory, capture_output=True, text=True, check=False)
        try:
            return int(json.loads(result.stdout)["metadata"]["vulnerabilities"]["total"])
        except (ValueError, KeyError, TypeError):
            return None


class AlertCheck:
    """Compares every open alert with the new lock files."""

    def __init__(self, root: Path, state: State, finder: ManifestFinder):
        self.root = root
        self.state = state
        self.finder = finder
        self.reverted = set(state.load("reverted.json", []))
        self.npm = {r["dir"]: r for r in state.load("npm.json", [])}
        self.unlocked_ok = {r["manifest"] for r in state.load("unlocked.json", []) if r["status"] == "pass"}
        self.comment_limited = {
            (c["manifest"], c["package"]) for c in state.load("changes.json", []) if c["kind"] == "lift_skipped"
        }

    def run(self) -> tuple[int, list[dict]]:
        fixed, still_open = 0, []
        locked_cache: dict[str, dict[str, str]] = {}
        for alert in Alerts(self.state).items:
            path = alert["manifest_path"]
            if not self.finder.in_scope(path):
                continue
            directory = str(Path(path).parent)
            if alert["ecosystem"] == "npm":
                result = self.npm.get(directory)
                if result and result["status"] == "fixed" and result.get("remaining") == 0:
                    fixed += 1
                elif not result:
                    still_open.append(self._row(alert, "npm: not processed"))
                elif result["status"] == "reverted":
                    still_open.append(self._row(alert, "npm: fix broke the build and was reverted"))
                else:
                    still_open.append(
                        self._row(alert, "npm: needs a breaking upgrade (`npm audit fix --force` is not used)")
                    )
                continue
            if alert["ecosystem"] != "pip":
                still_open.append(self._row(alert, f"ecosystem {alert['ecosystem']}"))
                continue
            if not alert["patched"]:
                still_open.append(self._row(alert, "no patch released"))
                continue
            manifest_rel = f"{directory}/pyproject.toml" if directory != "." else "pyproject.toml"
            if path.endswith("pyproject.toml"):
                # An alert on the declared range: fixed when every declaration now requires the patched version.
                if self._declared_safe(manifest_rel, alert["package"], alert["patched"]):
                    fixed += 1
                elif manifest_rel in self.reverted:
                    still_open.append(self._row(alert, "manifest failed its checks and was reverted"))
                else:
                    still_open.append(self._row(alert, "declared range still allows the vulnerable version"))
                continue
            if manifest_rel not in locked_cache:
                lock = self.root / directory / "uv.lock"
                locked_cache[manifest_rel] = (
                    Manifest(self.root, self.root / manifest_rel).locked_versions() if lock.exists() else {}
                )
            version = parse_version(locked_cache[manifest_rel].get(canonicalize_name(alert["package"])))
            patched = parse_version(alert["patched"])
            if version is None or (patched and version >= patched):
                fixed += 1
                continue
            if manifest_rel in self.reverted:
                reason = "manifest failed its checks and was reverted"
            elif (manifest_rel, canonicalize_name(alert["package"])) in self.comment_limited:
                reason = "documented limit"
            else:
                reason = "held back by another package's limit"
            still_open.append(self._row(alert, reason))
        return fixed, still_open

    def _declared_safe(self, manifest_rel: str, package: str, patched: str) -> bool:
        path = self.root / manifest_rel
        target = parse_version(patched)
        if not path.exists() or target is None:
            return False
        name = canonicalize_name(package)
        found = False
        for text in Manifest(self.root, path).requirement_strings():
            try:
                requirement = Requirement(text)
            except InvalidRequirement:
                continue
            if canonicalize_name(requirement.name) != name:
                continue
            found = True
            floors = [
                parse_version(spec.version)
                for spec in requirement.specifier
                if spec.operator in {">=", ">", "==", "==="}
            ]
            if not any(floor is not None and floor >= target for floor in floors):
                return False
        return found

    @staticmethod
    def _row(alert: dict, reason: str) -> dict:
        return {
            "package": alert["package"],
            "manifest": alert["manifest_path"],
            "severity": alert["severity"],
            "patched": alert["patched"],
            "reason": reason,
        }


class Reporter:
    """Command: write the PR body and the run summary."""

    MARKER = "<!-- ak-dep-update manifests={count} run={run} -->"
    SEVERITY_ORDER: ClassVar[dict[str, int]] = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    def __init__(self, root: Path, finder: ManifestFinder, state: State, run_id: str, dry_run: bool):
        self.root = root
        self.finder = finder
        self.manifests = finder.find()
        self.state = state
        self.run_id = run_id
        self.dry_run = dry_run

    def _changed_files(self) -> list[str]:
        diff = subprocess.run(["git", "diff", "--name-only"], cwd=self.root, capture_output=True, text=True, check=True)
        pattern = re.compile(r"(^|/)(pyproject\.toml|uv\.lock|package\.json|package-lock\.json)$")
        return [item for item in diff.stdout.split() if pattern.search(item)]

    def _version_rows(self, changed_dirs: set[str]) -> tuple[list[str], int]:
        snapshot = self.state.load("snapshot.json", {})
        rows, transitive = [], 0
        for manifest in self.manifests:
            if manifest.relative_dir not in changed_dirs:
                continue
            before, after = snapshot.get(manifest.relative, {}), manifest.locked_versions()
            direct = manifest.direct_names()
            for name, version in sorted(after.items()):
                if before.get(name) in (None, version):
                    continue
                if name in direct:
                    rows.append(f"| {name} | {manifest.relative} | {before[name]} -> {version} |")
                else:
                    transitive += 1
        return rows, transitive

    def _open_lines(self, still_open: list[dict], limit: int) -> list[str]:
        grouped: dict[tuple[str, str, str], list[str]] = {}
        for row in still_open:
            grouped.setdefault((row["package"], row["severity"], row["reason"]), []).append(row["manifest"])
        ordered = sorted(grouped.items(), key=lambda item: (self.SEVERITY_ORDER.get(item[0][1], 9), item[0][0]))
        lines = [
            f"- `{package}` ({severity}): {reason} — {len(set(manifests))} manifest(s)"
            for (package, severity, reason), manifests in ordered[:limit]
        ]
        if len(ordered) > limit:
            lines.append(f"- ... and {len(ordered) - limit} more groups (see the run summary artifact)")
        return lines

    def run(self) -> int:
        changes = self.state.load("changes.json", [])
        results = self.state.load("results.json", [])
        reverted = set(self.state.load("reverted.json", []))
        changed_files = self._changed_files()
        changed_dirs = {str(Path(item).parent) for item in changed_files}
        live = [c for c in changes if c["manifest"] not in reverted]
        counts = {
            kind: sum(1 for c in live if c["kind"] == kind)
            for kind in ("restrict", "lift", "security", "security_only")
        }
        skipped = [c for c in changes if c["kind"] == "lift_skipped"]
        rows, transitive = self._version_rows(changed_dirs)
        failed = [r for r in results if r["manifest"] in reverted]
        security_only = [r for r in results if r.get("note") == "security_only" and r["status"] == "pass"]
        tests_before = [r for r in results if r.get("note") == "tests_failing_before"]
        fixed_alerts, still_open = AlertCheck(self.root, self.state, self.finder).run()
        npm = self.state.load("npm.json", [])
        ak_py_ok = any(r["manifest"].startswith("ak-py/") and r["status"] == "pass" for r in results)

        title = "chore(deps): update dependency versions and fix vulnerabilities"
        summary = {"title": title, "files": len(changed_files), "has_changes": bool(changed_files)}
        self.state.save("summary.json", summary)
        self.state.save("still-open.json", still_open)

        lines = [
            "## Description",
            (
                f"Weekly dependency update. {counts['restrict']} dependencies got an upper limit, {counts['lift']} limits "
                f"were raised, {counts['security'] + counts['security_only']} limits were moved to a patched version, and "
                f"{len(rows)} direct dependencies changed version ({transitive} indirect). "
                f"{fixed_alerts} open Dependabot alerts are fixed by this PR; {len(still_open)} remain."
            ),
            "",
            "## Type of Change",
            "- [x] Bug fix (non-breaking change which fixes an issue)",
            "- [ ] New feature (non-breaking change which adds functionality)",
            "- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)",
            "- [ ] Documentation update",
            "- [ ] Refactoring (no functional changes)",
            "- [ ] Performance improvement",
            "- [ ] Test update",
            "- [ ] CI/CD update",
            "- [x] Other (please describe): Dependency version handling",
            "",
            "## Related Issues",
            "Fixes #",
            "Relates to #659, #824",
            "",
            "## Changes Made",
            f"- Upper limits added: {counts['restrict']}",
            f"- Limits raised to the latest release: {counts['lift']}",
            f"- Limits moved to a patched version: {counts['security'] + counts['security_only']}",
            f"- Manifests kept at security fixes only (full update failed): {len(security_only)}",
            "- npm: " + (", ".join(f"`{r['dir']}` {r['status']}" for r in npm) or "nothing to do"),
            f"- Files changed: {len(changed_files)}",
            "",
        ]
        if rows:
            lines += ["| Package | Manifest | Old -> New |", "|---|---|---|", *rows[:300], ""]
            if len(rows) > 300:
                lines += [f"... and {len(rows) - 300} more rows.", ""]
        lines += [
            "## Testing",
            f"- [{'x' if ak_py_ok else ' '}] Unit tests pass locally",
            "- [ ] Integration tests pass locally",
            "- [ ] Manual testing completed",
            "- [ ] New tests added for changes",
            (
                "Per manifest: `uv lock --upgrade`. ak-py: `uv sync`, `uv run pytest`, `make lint-check`. "
                "Others: `uv sync --frozen`, and `uv run pytest` where the manifest has tests "
                f"({len(tests_before)} manifests had tests that already failed on the base commit; not counted as failures). "
                "npm: `npm ci` and `npm run build`."
            ),
            "",
            "## Checklist",
            "- [x] My code follows the project's style guidelines",
            "- [x] I have performed a self-review of my code",
            "- [ ] I have commented my code, particularly in hard-to-understand areas",
            "- [ ] I have made corresponding changes to the documentation",
            "- [ ] My changes generate no new warnings",
            "- [ ] I have added tests that prove my fix is effective or that my feature works",
            f"- [{'x' if ak_py_ok else ' '}] New and existing unit tests pass locally with my changes",
            "- [ ] Any dependent changes have been merged and published",
            "",
            "## Screenshots (if applicable)",
            "N/A",
            "",
            "## Additional Notes",
        ]
        for result in failed:
            first = next((line for line in reversed(result["tail"]) if line.strip()), "")
            lines.append(f"- Kept as before: `{result['manifest']}` failed at {result['step']}: {first[:160]}")
        for result in security_only:
            lines.append(f"- Security fixes only: `{result['manifest']}` (the full update failed its checks)")
        for item in skipped:
            lines.append(f"- Limit not raised: `{item['package']}` in `{item['manifest']}` ({item['note']})")
        if still_open:
            lines += ["", "Still open alerts (grouped):", *self._open_lines(still_open, 60)]
        lines += [
            "- Rollback: revert this PR.",
            f"- Hidden marker: {self.MARKER.format(count=len(changed_dirs), run=self.run_id)}",
        ]
        self.state.path("pr-body.md").write_text("\n".join(lines) + "\n")

        status = "dry_run_ok" if self.dry_run else ("ready" if changed_files else "no updates")
        summary_lines = [
            "## Status",
            status,
            "",
            (
                f"Files changed: {len(changed_files)}. Limits added: {counts['restrict']}. Limits raised: {counts['lift']}. "
                f"Security limits: {counts['security'] + counts['security_only']}. Direct version changes: {len(rows)}. "
                f"Reverted manifests: {len(failed)}. Alerts fixed: {fixed_alerts}. Alerts still open: {len(still_open)}."
            ),
            "",
            "## Kept as before",
            *(f"- {r['manifest']}: failed at {r['step']}" for r in failed),
            "",
            "## Security fixes only",
            *(f"- {r['manifest']}" for r in security_only),
            "",
            "## Still open alerts",
            *self._open_lines(still_open, 500),
        ]
        self.state.path("update-summary.md").write_text("\n".join(summary_lines) + "\n")
        print(json.dumps(dict(summary, alerts_fixed=fixed_alerts, alerts_open=len(still_open))))
        return 0


class Snapshotter:
    """Command: save the locked versions of every manifest and the base commit."""

    def __init__(self, root: Path, manifests: list[Manifest], state: State):
        self.root = root
        self.manifests = manifests
        self.state = state

    def run(self) -> int:
        self.state.save("snapshot.json", {m.relative: m.locked_versions() for m in self.manifests})
        commit = "HEAD"
        if (self.root / ".git").exists():
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True, text=True, check=True
            ).stdout.strip()
        self.state.save("snapshot-meta.json", {"commit": commit})
        for name in (
            "changes.json",
            "results.json",
            "failures.json",
            "reverted.json",
            "unlocked.json",
            "npm.json",
            "still-open.json",
        ):
            self.state.path(name).unlink(missing_ok=True)
        print(f"snapshot of {len(self.manifests)} manifests at {commit[:12]}")
        return 0


COMMANDS = [
    "snapshot",
    "alerts",
    "restrict",
    "lift",
    "secure",
    "validate",
    "failures",
    "security-fallback",
    "finalize",
    "unlocked",
    "npm",
    "report",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--root", default=".", help="repository root")
    parser.add_argument("--state", default="/tmp/dep-state", help="state directory")
    parser.add_argument("--paths", default="", help="comma-separated path prefixes (empty = everything)")
    parser.add_argument("--packages", default="", help="restrict/lift only: package names (empty = all)")
    parser.add_argument("--repo", default=os.environ.get("REPO", "yaalalabs/agent-kernel"), help="alerts: owner/name")
    parser.add_argument("--level", choices=["lock", "full"], default="full")
    parser.add_argument("--upgrade", action="store_true", help="validate: run uv lock --upgrade")
    parser.add_argument("--only-failed", action="store_true", help="validate: only manifests that failed before")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--run-id", default="local", help="report only")
    parser.add_argument("--dry-run", action="store_true", help="report only")
    return parser


def split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.root).resolve()
    state = State(Path(args.state))
    finder = ManifestFinder(root, split(args.paths))
    manifests = finder.find()
    packages = {canonicalize_name(name) for name in split(args.packages)}
    if args.command == "snapshot":
        return Snapshotter(root, manifests, state).run()
    if args.command == "alerts":
        return AlertFetcher(state, args.repo).run()
    if args.command == "restrict":
        return Restricter(manifests, state, packages).run()
    if args.command == "lift":
        return Lifter(manifests, state, packages).run()
    if args.command == "secure":
        return Securer(manifests, state).run()
    if args.command == "validate":
        return Validator(manifests, state, args.level, args.upgrade, args.only_failed, args.workers).run()
    if args.command == "failures":
        print(sum(1 for r in state.load("results.json", []) if r["status"] == "fail"))
        return 0
    if args.command == "security-fallback":
        return SecurityFallback(manifests, state, args.workers).run()
    if args.command == "finalize":
        return Finalizer(manifests, state).run()
    if args.command == "unlocked":
        return UnlockedFixer(finder.unlocked(), state).run()
    if args.command == "npm":
        return NpmFixer(root, finder.npm_dirs(), state).run()
    return Reporter(root, finder, state, args.run_id, args.dry_run).run()


if __name__ == "__main__":
    sys.exit(main())
