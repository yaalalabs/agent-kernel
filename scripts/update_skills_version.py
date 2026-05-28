#!/usr/bin/env python3
"""Update hardcoded Agent Kernel versions in published skills."""

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable


VERSION_PATTERN = r"\d+\.\d+\.\d+(?:(?:a|b|rc)\d+|-[A-Za-z0-9.-]+)?"


def discover_current_versions(skills_dir: Path) -> set[str]:
    """Collect current skill versions from SKILL metadata and evals.json files."""
    versions: set[str] = set()

    for skill_file in skills_dir.rglob("SKILL.md"):
        content = skill_file.read_text(encoding="utf-8")
        versions.update(
            re.findall(rf'^\s*version:\s*"({VERSION_PATTERN})"\s*$', content, flags=re.MULTILINE)
        )

    for eval_file in skills_dir.rglob("evals/evals.json"):
        content = eval_file.read_text(encoding="utf-8")
        versions.update(
            re.findall(rf'"version"\s*:\s*"({VERSION_PATTERN})"', content)
        )

    return versions


def _replace_for_skill_markdown(content: str, old_version: str, new_version: str) -> tuple[str, int]:
    replacements = 0

    content, count = re.subn(
        rf'(^\s*version:\s*")({re.escape(old_version)})("\s*$)',
        lambda m: f'{m.group(1)}{new_version}{m.group(3)}',
        content,
        flags=re.MULTILINE,
    )
    replacements += count

    content, count = re.subn(
        rf'(agentkernel(?:\[[^\]]*\])?\s*>=\s*)({re.escape(old_version)})\b',
        lambda m: f"{m.group(1)}{new_version}",
        content,
    )
    replacements += count

    content, count = re.subn(
        rf'(Use current module version \(`)({re.escape(old_version)})(`\))',
        lambda m: f'{m.group(1)}{new_version}{m.group(3)}',
        content,
    )
    replacements += count

    content, count = re.subn(
        rf'(\bversion\s*=\s*")({re.escape(old_version)})(")',
        lambda m: f'{m.group(1)}{new_version}{m.group(3)}',
        content,
    )
    replacements += count

    return content, replacements


def _replace_for_eval_json(content: str, old_version: str, new_version: str) -> tuple[str, int]:
    replacements = 0

    content, count = re.subn(
        rf'("version"\s*:\s*")({re.escape(old_version)})(")',
        lambda m: f'{m.group(1)}{new_version}{m.group(3)}',
        content,
    )
    replacements += count

    content, count = re.subn(
        rf'(agentkernel(?:\[[^\]]*\])?\s*>=\s*)({re.escape(old_version)})\b',
        lambda m: f"{m.group(1)}{new_version}",
        content,
    )
    replacements += count

    content, count = re.subn(
        rf'("\s*>=\s*)({re.escape(old_version)})("\s*)',
        lambda m: f'{m.group(1)}{new_version}{m.group(3)}',
        content,
    )
    replacements += count

    return content, replacements


def update_skills_versions(skills_dir: Path, new_version: str, dry_run: bool = False) -> tuple[int, int]:
    """Update hardcoded versions in SKILL.md and evals/evals.json files."""
    old_versions = discover_current_versions(skills_dir)
    if not old_versions:
        return 0, 0

    files_to_process: list[Path] = sorted(skills_dir.rglob("SKILL.md")) + sorted(
        skills_dir.rglob("evals/evals.json")
    )

    modified_files = 0
    total_replacements = 0

    for file_path in files_to_process:
        content = file_path.read_text(encoding="utf-8")
        original = content
        file_replacements = 0

        for old_version in sorted(old_versions, reverse=True):
            if old_version == new_version:
                continue

            if file_path.name == "SKILL.md":
                content, count = _replace_for_skill_markdown(content, old_version, new_version)
            else:
                content, count = _replace_for_eval_json(content, old_version, new_version)
            file_replacements += count

        if content != original:
            modified_files += 1
            total_replacements += file_replacements
            if not dry_run:
                file_path.write_text(content, encoding="utf-8")

    return modified_files, total_replacements


def _is_valid_version(version: str) -> bool:
    return bool(re.fullmatch(VERSION_PATTERN, version))


def _format_versions(versions: Iterable[str]) -> str:
    sorted_versions = sorted(versions)
    return ", ".join(sorted_versions) if sorted_versions else "(none)"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update hardcoded versions in ak-py/src/agentkernel/skills"
    )
    parser.add_argument("--version", required=True, help="Target version (for example: 0.5.0, 0.5.0a1)")
    parser.add_argument(
        "--skills-dir",
        type=Path,
        help="Path to skills directory (default: ../ak-py/src/agentkernel/skills relative to this script)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show summary without writing files")

    args = parser.parse_args()

    if not _is_valid_version(args.version):
        print(f"Error: invalid version '{args.version}'", file=sys.stderr)
        sys.exit(1)

    if args.skills_dir:
        skills_dir = args.skills_dir
    else:
        skills_dir = Path(__file__).parent.parent / "ak-py" / "src" / "agentkernel" / "skills"

    if not skills_dir.exists():
        print(f"Error: skills directory not found: {skills_dir}", file=sys.stderr)
        sys.exit(1)

    current_versions = discover_current_versions(skills_dir)
    print(f"Skills directory: {skills_dir}")
    print(f"Discovered current versions: {_format_versions(current_versions)}")
    print(f"Target version: {args.version}")
    if args.dry_run:
        print("Dry run mode: no files will be modified")

    modified_files, replacements = update_skills_versions(skills_dir, args.version, dry_run=args.dry_run)

    print()
    if args.dry_run:
        print(f"Would modify {modified_files} file(s), {replacements} replacement(s)")
    else:
        print(f"Modified {modified_files} file(s), {replacements} replacement(s)")


if __name__ == "__main__":
    main()
