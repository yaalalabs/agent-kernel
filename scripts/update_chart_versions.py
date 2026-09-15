#!/usr/bin/env python3
"""
Update the published Helm chart version in example install commands.

The examples, the docs site, the bundled ak-cloud-deploy skill, the chart's own Chart.yaml
description, and the root README (what GitHub renders on the chart's GHCR package page) install
the Agent Kernel chart from its OCI artifact: `oci://ghcr.io/yaalalabs/charts/agent-kernel
--version X.Y.Z` in READMEs and docs pages, and a `CHART_VERSION="X.Y.Z"` variable in the
examples' deploy/deploy.sh scripts. The publish workflow runs this script for each release so
those pins track the chart version it is about to publish, the way update_terraform_versions.py
tracks the Terraform module versions.
"""

import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple

CHART_REF = "oci://ghcr.io/yaalalabs/charts/agent-kernel"

# Chart versions are SemVer 2 (Helm rejects anything else): the release tag minus its "v",
# so prereleases arrive hyphenated (1.0.0-a1), never in PEP 440 form (1.0.0a1).
SEMVER = r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?"
SEMVER_PATTERN = re.compile(rf"^{SEMVER}$")

# The chart reference followed by its --version flag and a concrete version. Only that version
# token is rewritten, so surrounding prose, shell continuations, and comment markers survive
# untouched, and documentation placeholders such as `--version <version>` are left alone.
CHART_VERSION_PATTERN = re.compile(rf"({re.escape(CHART_REF)}\s+--version\s+)({SEMVER})\b")

# The example deploy scripts keep the pin in a variable beside the chart reference. Only shell
# scripts that name the chart qualify, so an unrelated CHART_VERSION variable is left alone.
SHELL_VERSION_PATTERN = re.compile(rf'^(\s*CHART_VERSION=")({SEMVER})(")', re.MULTILINE)

FILE_GLOBS = ("*.md", "*.yaml", "*.yml", "*.sh")
FILE_SUFFIXES = tuple(glob[1:] for glob in FILE_GLOBS)
# docs/docs is the live docs source (versioned_docs snapshots are frozen); the skills tree is
# packaged into the wheel, so the publish workflow runs this before building it. Entries may
# also name a single file: the root README.md is scanned because GitHub renders it on the
# chart's GHCR package page, where its install snippet stands in for the missing helm command.
DEFAULT_DIRECTORIES = [
    "examples",
    "ak-deployment",
    "docs/docs",
    "ak-py/src/agentkernel/skills",
    "README.md",
]
DEFAULT_EXCLUDES = [".venv", "node_modules", ".terraform", "__pycache__", "versioned_docs"]


def find_files(directories: List[str], exclude_patterns: List[str] = None) -> List[Path]:
    """Find every Markdown, YAML, and shell file under the directories, minus excluded path
    parts. An entry that names a file is taken as given when its suffix qualifies."""
    if exclude_patterns is None:
        exclude_patterns = DEFAULT_EXCLUDES

    files = []
    for directory in directories:
        dir_path = Path(directory)
        if not dir_path.exists():
            print(f"Warning: Path {directory} does not exist, skipping...")
            continue

        if dir_path.is_file():
            if dir_path.suffix in FILE_SUFFIXES and not any(pattern in dir_path.parts for pattern in exclude_patterns):
                files.append(dir_path)
            continue

        for glob in FILE_GLOBS:
            for path in dir_path.rglob(glob):
                if any(pattern in path.parts for pattern in exclude_patterns):
                    continue
                files.append(path)

    return sorted(set(files))


def patterns_for(file_path: Path, content: str) -> List[re.Pattern]:
    """The pin patterns that apply to a file: the install-command form everywhere, plus the
    CHART_VERSION variable in shell scripts that reference the chart."""
    patterns = [CHART_VERSION_PATTERN]
    if file_path.suffix == ".sh" and CHART_REF in content:
        patterns.append(SHELL_VERSION_PATTERN)
    return patterns


def count_stale_references(content: str, new_version: str, patterns: List[re.Pattern] = None) -> int:
    """Count chart references whose pinned version (group 2 of each pattern) differs from new_version."""
    if patterns is None:
        patterns = [CHART_VERSION_PATTERN]
    return sum(1 for pattern in patterns for match in pattern.finditer(content) if match.group(2) != new_version)


def _repin(match: re.Match, new_version: str) -> str:
    """Rewrite only the version token (group 2) of a match, keeping everything around it."""
    whole = match.group(0)
    start, end = match.start(2) - match.start(0), match.end(2) - match.start(0)
    return whole[:start] + new_version + whole[end:]


def update_chart_versions(file_path: Path, new_version: str) -> Tuple[bool, int]:
    """
    Pin every chart reference in a file to new_version.

    Returns: (was_modified, number_of_updates)
    """
    content = file_path.read_text(encoding="utf-8")
    patterns = patterns_for(file_path, content)
    update_count = count_stale_references(content, new_version, patterns)
    if update_count == 0:
        return False, 0

    updated = content
    for pattern in patterns:
        updated = pattern.sub(lambda match: _repin(match, new_version), updated)
    file_path.write_text(updated, encoding="utf-8")
    return True, update_count


def main():
    parser = argparse.ArgumentParser(
        description=f"Pin every `{CHART_REF} --version` reference to a new chart version"
    )
    parser.add_argument(
        "--version",
        required=True,
        help="New chart version to set, SemVer 2 as on the release tag (e.g., 0.9.1 or 1.0.0-b2)",
    )
    parser.add_argument(
        "--directories",
        nargs="+",
        default=DEFAULT_DIRECTORIES,
        help=f"Directories (or individual files) to search for .md/.yaml/.yml/.sh files (default: {' '.join(DEFAULT_DIRECTORIES)})",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=DEFAULT_EXCLUDES,
        help=f"Path segments to exclude from search (default: {' '.join(DEFAULT_EXCLUDES)})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without making changes",
    )

    args = parser.parse_args()

    if not SEMVER_PATTERN.match(args.version):
        print(
            f"Error: '{args.version}' is not a SemVer 2 chart version (use the tag form, e.g. 1.0.0-a1)",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"🔍 Searching for .md/.yaml/.yml/.sh files in: {', '.join(args.directories)}")
    print(f"📌 Excluding path segments: {', '.join(args.exclude)}")
    print(f"🎯 Target chart version: {args.version}")

    if args.dry_run:
        print("🔎 DRY RUN MODE - No files will be modified")

    print()

    files = find_files(args.directories, args.exclude)
    print(f"Found {len(files)} files to scan")
    print()

    total_modified = 0
    total_updates = 0

    for file_path in files:
        if args.dry_run:
            content = file_path.read_text(encoding="utf-8")
            stale = count_stale_references(content, args.version, patterns_for(file_path, content))
            if stale:
                print(f"📝 Would update {file_path} ({stale} references)")
                total_modified += 1
                total_updates += stale
        else:
            was_modified, num_updates = update_chart_versions(file_path, args.version)
            if was_modified:
                print(f"✅ Updated {file_path} ({num_updates} references)")
                total_modified += 1
                total_updates += num_updates

    print()
    print("=" * 60)
    if args.dry_run:
        print(f"Would update {total_updates} chart references in {total_modified} files")
    else:
        print(f"✅ Updated {total_updates} chart references in {total_modified} files")

    if total_modified == 0:
        print(f"ℹ️  No `{CHART_REF} --version` references needed updating")


if __name__ == "__main__":
    main()
