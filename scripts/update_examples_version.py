#!/usr/bin/env python3
"""
Update agentkernel version references in example pyproject.toml files.

This script finds all pyproject.toml files in the examples/ directory and updates
the agentkernel dependency version constraints to match the specified version.
It also regenerates uv.lock files to ensure they reflect the new version.
"""

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path


def update_pyproject_version(file_path: Path, new_version: str) -> bool:
    """
    Update agentkernel version in a pyproject.toml file.
    
    Args:
        file_path: Path to the pyproject.toml file
        new_version: The new version to set (e.g., "0.1.0", "0.2.0a1")
    
    Returns:
        True if the file was modified, False otherwise
    """
    content = file_path.read_text()
    original_content = content

    # Pattern to match agentkernel dependencies with version constraints
    # Matches patterns like: agentkernel[extras]>=0.1.0a1
    pattern = r'(agentkernel(?:\[[^\]]+\])?)>=[\d\.]+(?:a\d+|b\d+|rc\d+)?'
    replacement = rf'\1>={new_version}'

    content = re.sub(pattern, replacement, content)

    if content != original_content:
        file_path.write_text(content)
        return True

    return False


def find_example_pyproject_files(examples_dir: Path) -> list[Path]:
    """
    Find all pyproject.toml files in the examples directory.
    
    Args:
        examples_dir: Path to the examples directory
    
    Returns:
        List of paths to pyproject.toml files (excluding venv, terraform, etc.)
    """
    # Directories to exclude
    exclude_patterns = {'.venv', '__pycache__', '.terraform', 'dist', 'node_modules', '.git'}
    
    all_files = []
    for pyproject_file in examples_dir.rglob("pyproject.toml"):
        # Skip if any parent directory matches exclude patterns
        if any(part in exclude_patterns for part in pyproject_file.parts):
            continue
        all_files.append(pyproject_file)
    
    return sorted(all_files)


def regenerate_uv_lock(project_dir: Path, dry_run: bool = False, retries: int = 3, retry_delay: int = 10) -> bool:
    """
    Regenerate uv.lock file for a project with retry logic.
    
    Args:
        project_dir: Path to the project directory containing pyproject.toml
        dry_run: If True, don't actually run the command
        retries: Number of retry attempts (default: 3)
        retry_delay: Delay in seconds between retries (default: 10)
    
    Returns:
        True if successful, False otherwise
    """
    if dry_run:
        return True

    for attempt in range(retries):
        try:
            # Run uv lock in the project directory
            result = subprocess.run(
                ["uv", "lock"],
                cwd=project_dir,
                check=True,
                capture_output=True,
                text=True,
                timeout=60  # Add timeout to prevent hanging
            )
            return True
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.lower()
            # Check if it's a package availability issue
            is_availability_issue = any([
                "not found" in error_msg,
                "no version" in error_msg,
                "could not find" in error_msg,
                "no solution found" in error_msg,
                "only agentkernel" in error_msg and "is available" in error_msg,
                "unsatisfiable" in error_msg and "agentkernel" in error_msg
            ])
            
            if attempt < retries - 1 and is_availability_issue:
                print(f"  Attempt {attempt + 1}/{retries} failed. Package may not be available yet. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                continue
            else:
                print(f"  Error running uv lock: {e.stderr}", file=sys.stderr)
                return False
        except subprocess.TimeoutExpired:
            print(f"  Error: uv lock timed out after 60 seconds", file=sys.stderr)
            return False
        except FileNotFoundError:
            print("  Error: 'uv' command not found. Please install uv.", file=sys.stderr)
            return False
    
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Update agentkernel version in example pyproject.toml files"
    )
    parser.add_argument(
        "--version",
        required=True,
        help="New version to set (e.g., 0.1.0, 0.2.0a1)"
    )
    parser.add_argument(
        "--examples-dir",
        type=Path,
        help="Path to examples directory (default: ../examples relative to this script)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without making modifications"
    )
    parser.add_argument(
        "--skip-lock",
        action="store_true",
        help="Skip regenerating uv.lock files"
    )
    parser.add_argument(
        "--force-lock",
        action="store_true",
        help="Force regenerate uv.lock files even if pyproject.toml hasn't changed"
    )
    parser.add_argument(
        "--lock-retries",
        type=int,
        default=3,
        help="Number of retry attempts for lock regeneration (default: 3)"
    )
    parser.add_argument(
        "--lock-retry-delay",
        type=int,
        default=10,
        help="Delay in seconds between lock regeneration retries (default: 10)"
    )

    args = parser.parse_args()

    # Determine examples directory
    if args.examples_dir:
        examples_dir = args.examples_dir
    else:
        # Default to ../examples relative to this script
        script_dir = Path(__file__).parent
        examples_dir = script_dir.parent / "examples"

    if not examples_dir.exists():
        print(f"Error: Examples directory not found: {examples_dir}", file=sys.stderr)
        sys.exit(1)

    # Find all pyproject.toml files
    pyproject_files = find_example_pyproject_files(examples_dir)

    if not pyproject_files:
        print(f"No pyproject.toml files found in {examples_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(pyproject_files)} pyproject.toml file(s) in examples/")
    print(f"Updating agentkernel version to: {args.version}")
    print()

    modified_count = 0
    lock_success_count = 0
    lock_fail_count = 0

    for file_path in pyproject_files:
        relative_path = file_path.relative_to(examples_dir.parent)
        project_dir = file_path.parent

        if args.dry_run:
            content = file_path.read_text()
            pattern = r'(agentkernel(?:\[[^\]]+\])?)>=[\d\.]+(?:a\d+|b\d+|rc\d+)?'
            matches = re.findall(pattern, content)

            if matches:
                print(f"Would update: {relative_path}")
                for match in matches:
                    print(f"  - {match}>=... → {match}>={args.version}")
                if not args.skip_lock:
                    print(f"  - Would regenerate uv.lock")
                modified_count += 1
        else:
            was_modified = update_pyproject_version(file_path, args.version)

            if was_modified:
                print(f"✓ Updated: {relative_path}")
                modified_count += 1

                # Regenerate uv.lock file
                if not args.skip_lock:
                    print(f"  Regenerating uv.lock...")
                    if regenerate_uv_lock(project_dir, args.dry_run, args.lock_retries, args.lock_retry_delay):
                        print(f"  ✓ Lock file regenerated")
                        lock_success_count += 1
                    else:
                        print(f"  ✗ Failed to regenerate lock file")
                        lock_fail_count += 1
            else:
                # File wasn't modified but we might need to force lock regeneration
                if args.force_lock and not args.skip_lock:
                    print(f"  {relative_path} (no version change, regenerating lock)")
                    print(f"  Regenerating uv.lock...")
                    if regenerate_uv_lock(project_dir, args.dry_run, args.lock_retries, args.lock_retry_delay):
                        print(f"  ✓ Lock file regenerated")
                        lock_success_count += 1
                    else:
                        print(f"  ✗ Failed to regenerate lock file")
                        lock_fail_count += 1
                else:
                    print(f"  Skipped: {relative_path} (no changes needed)")

    print()
    if args.dry_run:
        print(f"Dry run complete. {modified_count} file(s) would be modified.")
    else:
        print(f"Updated {modified_count} file(s).")
        if not args.skip_lock:
            print(f"Regenerated {lock_success_count} lock file(s).")
            if lock_fail_count > 0:
                print(f"Failed to regenerate {lock_fail_count} lock file(s).", file=sys.stderr)
                return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
