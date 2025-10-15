#!/usr/bin/env python3
"""
Version bumping script for pyproject.toml

This script handles semantic versioning with support for:
- Major, minor, and patch version bumps
- Pre-release versions (alpha, beta)
- Automatic pre-release number determination
- Proper version number increments

Usage:
    python bump_version.py --bump patch
    python bump_version.py --bump minor --prerelease alpha --auto-prerelease-number
    python bump_version.py --bump major --prerelease beta --prerelease-number 2
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Optional, Tuple


def parse_version(version: str) -> Tuple[int, int, int, Optional[str], Optional[int]]:
    """
    Parse a semantic version string.
    
    Returns: (major, minor, patch, prerelease_type, prerelease_number)
    Examples:
        "1.2.3" -> (1, 2, 3, None, None)
        "1.2.3a1" -> (1, 2, 3, "a", 1)
        "1.2.3b2" -> (1, 2, 3, "b", 2)
        "0.1.0a1" -> (0, 1, 0, "a", 1)
    """
    # Match version pattern: major.minor.patch[prerelease_type][prerelease_number]
    pattern = r'^(\d+)\.(\d+)\.(\d+)([ab])?(\d+)?$'
    match = re.match(pattern, version)

    if not match:
        raise ValueError(f"Invalid version format: {version}")

    major, minor, patch, prerelease_type, prerelease_num = match.groups()

    return (
        int(major),
        int(minor),
        int(patch),
        prerelease_type,
        int(prerelease_num) if prerelease_num else None
    )


def bump_version(
        current_version: str,
        bump_type: str,
        prerelease: Optional[str] = None,
        prerelease_number: Optional[int] = None,
        auto_increment_prerelease: bool = False
) -> str:
    """
    Bump a semantic version.
    
    Rules:
    1. From stable to stable: bump base version normally
    2. From stable to prerelease: bump base version, add prerelease suffix
    3. From prerelease to stable: keep base version, remove prerelease suffix
    4. From prerelease to prerelease:
       - If the base version would need to change, change it and reset prerelease to 1
       - If the base version stays same, increment prerelease number, keep prerelease type
    
    Args:
        current_version: Current version string (e.g., "1.2.3" or "1.2.3a1")
        bump_type: One of "major", "minor", or "patch"
        prerelease: Pre-release type ("alpha" or "beta") or None for stable
        prerelease_number: Pre-release number (default: 1)
        auto_increment_prerelease: If True, auto-increment prerelease number based on current version
    
    Returns:
        New version string
    """
    major, minor, patch, current_pre, current_pre_num = parse_version(current_version)

    # Convert prerelease string to shorthand
    pre_map = {"alpha": "a", "beta": "b", "": None, None: None}
    pre_short = pre_map.get(prerelease)

    # Start with current base version
    new_major, new_minor, new_patch = major, minor, patch

    if current_pre and not pre_short:
        # Case 3: From prerelease to stable - keep base version, remove prerelease
        pass
    elif not current_pre and pre_short:
        # Case 2: From stable to prerelease - bump base version
        if bump_type == "major":
            new_major += 1
            new_minor = 0
            new_patch = 0
        elif bump_type == "minor":
            new_minor += 1
            new_patch = 0
        elif bump_type == "patch":
            new_patch += 1
    elif not current_pre and not pre_short:
        # Case 1: From stable to stable - bump base version
        if bump_type == "major":
            new_major += 1
            new_minor = 0
            new_patch = 0
        elif bump_type == "minor":
            new_minor += 1
            new_patch = 0
        elif bump_type == "patch":
            new_patch += 1
    else:
        # Case 4: From prerelease to prerelease
        # Determine if base version needs to change based on bump type
        needs_version_bump = False

        if bump_type == "major":
            # Major bump from prerelease: only bump if not on X.0.0
            # e.g., 2.0.0b1 + major should go to 2.0.0b2 (already on major boundary)
            #       0.2.0a1 + major should go to 1.0.0a1 (not on major boundary)
            if minor != 0 or patch != 0:
                needs_version_bump = True
        elif bump_type == "minor":
            # Minor bump from prerelease: only bump if not on X.Y.0
            # e.g., 0.2.0a1 + minor should go to 0.2.0a2 (already on minor boundary)
            #       0.1.1a1 + minor should go to 0.2.0a1 (not on minor boundary)
            if patch != 0:
                needs_version_bump = True
        elif bump_type == "patch":
            # Patch bump from prerelease: never bump base version
            # e.g., 0.1.0a1 + patch should go to 0.1.0a2 (not 0.1.1a1)
            pass

        if needs_version_bump:
            if bump_type == "major":
                new_major += 1
                new_minor = 0
                new_patch = 0
            elif bump_type == "minor":
                new_minor += 1
                new_patch = 0

    # Determine pre-release number and type
    final_pre_short = None
    pre_num = None

    if pre_short:
        # Determine which prerelease type to use
        if current_pre and (new_major == major and new_minor == minor and new_patch == patch):
            # Staying on same base version - keep current prerelease type
            final_pre_short = current_pre
        else:
            # New base version - use requested prerelease type
            final_pre_short = pre_short

        if auto_increment_prerelease:
            # Check if we're staying on the same base version and prerelease type
            if (new_major == major and new_minor == minor and new_patch == patch
                    and current_pre == final_pre_short and current_pre_num is not None):
                # Increment existing prerelease number
                pre_num = current_pre_num + 1
            else:
                # New base version or different prerelease type, start at 1
                pre_num = 1
        else:
            pre_num = prerelease_number if prerelease_number else 1

    # Build new version
    new_version = f"{new_major}.{new_minor}.{new_patch}"

    if final_pre_short and pre_num:
        new_version += f"{final_pre_short}{pre_num}"

    return new_version


def update_pyproject_toml(file_path: Path, new_version: str) -> None:
    """Update the version field in pyproject.toml."""
    content = file_path.read_text()

    # Replace version line
    pattern = r'^version = ".*"$'
    replacement = f'version = "{new_version}"'

    new_content = re.sub(pattern, replacement, content, count=1, flags=re.MULTILINE)

    if new_content == content:
        raise ValueError("Could not find version field in pyproject.toml")

    file_path.write_text(new_content)


def main():
    parser = argparse.ArgumentParser(
        description="Bump version in pyproject.toml"
    )
    parser.add_argument(
        "--bump",
        choices=["major", "minor", "patch"],
        required=True,
        help="Type of version bump"
    )
    parser.add_argument(
        "--prerelease",
        choices=["alpha", "beta", ""],
        default="",
        help="Pre-release type (optional)"
    )
    parser.add_argument(
        "--prerelease-number",
        type=int,
        default=1,
        help="Pre-release number (default: 1, ignored if --auto-prerelease-number is set)"
    )
    parser.add_argument(
        "--auto-prerelease-number",
        action="store_true",
        help="Automatically determine pre-release number based on current version"
    )

    args = parser.parse_args()

    # Find pyproject.toml in current directory
    pyproject_path = Path("pyproject.toml")

    if not pyproject_path.exists():
        print(f"Error: pyproject.toml not found in {Path.cwd()}", file=sys.stderr)
        sys.exit(1)

    # Read current version
    try:
        import tomllib
    except ImportError:
        print("Error: tomllib not available", file=sys.stderr)
        sys.exit(1)

    with open(pyproject_path, "rb") as f:
        config = tomllib.load(f)

    current_version = config["project"]["version"]
    print(f"Current version: {current_version}")

    # Calculate new version
    prerelease = args.prerelease if args.prerelease else None
    new_version = bump_version(
        current_version,
        args.bump,
        prerelease,
        args.prerelease_number if prerelease and not args.auto_prerelease_number else None,
        auto_increment_prerelease=args.auto_prerelease_number
    )

    print(f"New version: {new_version}")

    # Update file
    update_pyproject_toml(pyproject_path, new_version)
    print(f"Updated {pyproject_path}")


if __name__ == "__main__":
    main()
