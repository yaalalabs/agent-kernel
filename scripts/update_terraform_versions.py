#!/usr/bin/env python3
"""
Update Terraform module versions in .tf files.

This script searches for Terraform module declarations that use yaalalabs/ak-* modules
and updates their version to the specified version.
"""

import argparse
import re
from pathlib import Path
from typing import List, Tuple


def find_tf_files(directories: List[str], exclude_patterns: List[str] = None) -> List[Path]:
    """Find all .tf files in the specified directories, excluding certain patterns."""
    if exclude_patterns is None:
        exclude_patterns = [".terraform"]
    
    tf_files = []
    for directory in directories:
        dir_path = Path(directory)
        if not dir_path.exists():
            print(f"Warning: Directory {directory} does not exist, skipping...")
            continue
            
        for tf_file in dir_path.rglob("*.tf"):
            # Check if file should be excluded
            should_exclude = any(pattern in str(tf_file) for pattern in exclude_patterns)
            if not should_exclude:
                tf_files.append(tf_file)
    
    return tf_files


def update_terraform_versions(file_path: Path, new_version: str) -> Tuple[bool, int]:
    """
    Update Terraform module versions in a file.
    
    Returns: (was_modified, number_of_updates)
    """
    with open(file_path, 'r') as f:
        content = f.read()
    
    original_content = content
    update_count = 0
    
    # Pattern to match entire module blocks
    # Module names can be quoted or unquoted: module "name" or module name
    module_pattern = re.compile(
        r'module\s+["\w]+\s*\{[^}]*\}',
        re.MULTILINE | re.DOTALL
    )
    
    def update_module_block(match):
        nonlocal update_count
        module_block = match.group(0)
        
        # Check if this module uses a yaalalabs/ak-* source
        source_pattern = r'source\s*=\s*"(?:app\.terraform\.io/|registry\.terraform\.io/)?yaalalabs/ak-[^"]+"'
        if not re.search(source_pattern, module_block):
            # Not a yaalalabs/ak-* module, return unchanged
            return module_block
        
        # Check if this module has a version attribute
        version_pattern = r'(\bversion\s*=\s*)"[^"]+"'
        if not re.search(version_pattern, module_block):
            # No version attribute, return unchanged
            return module_block
        
        # Update the version
        updated_block = re.sub(
            version_pattern,
            rf'\1"{new_version}"',
            module_block
        )
        
        if updated_block != module_block:
            update_count += 1
        
        return updated_block
    
    # Replace all module blocks
    content = module_pattern.sub(update_module_block, content)
    
    # Write back if changed
    if content != original_content:
        with open(file_path, 'w') as f:
            f.write(content)
        return True, update_count
    
    return False, 0


def main():
    parser = argparse.ArgumentParser(
        description="Update Terraform module versions for yaalalabs/ak-* modules"
    )
    parser.add_argument(
        "--version",
        required=True,
        help="New version to set (e.g., 0.1.2-b21)"
    )
    parser.add_argument(
        "--directories",
        nargs="+",
        default=["ak-deployment", "examples"],
        help="Directories to search for .tf files (default: ak-deployment examples)"
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=[".terraform"],
        help="Patterns to exclude from search (default: .terraform)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without making changes"
    )
    
    args = parser.parse_args()
    
    print(f"🔍 Searching for .tf files in: {', '.join(args.directories)}")
    print(f"📌 Excluding patterns: {', '.join(args.exclude)}")
    print(f"🎯 Target version: {args.version}")
    
    if args.dry_run:
        print("🔎 DRY RUN MODE - No files will be modified")
    
    print()
    
    # Find all .tf files
    tf_files = find_tf_files(args.directories, args.exclude)
    print(f"Found {len(tf_files)} .tf files to process")
    print()
    
    # Update versions
    total_modified = 0
    total_updates = 0
    
    for tf_file in tf_files:
        if args.dry_run:
            # In dry run, just check if file would be modified
            with open(tf_file, 'r') as f:
                content = f.read()
            pattern = re.compile(
                r'source\s*=\s*"(?:app\.terraform\.io/|registry\.terraform\.io/)?yaalalabs/ak-[^"]+"\s*\n\s*\bversion\s*=\s*"[^"]+"',
                re.MULTILINE
            )
            matches = pattern.findall(content)
            if matches:
                print(f"📝 Would update {tf_file} ({len(matches)} modules)")
                total_modified += 1
                total_updates += len(matches)
        else:
            was_modified, num_updates = update_terraform_versions(tf_file, args.version)
            if was_modified:
                print(f"✅ Updated {tf_file} ({num_updates} modules)")
                total_modified += 1
                total_updates += num_updates
    
    print()
    print("=" * 60)
    if args.dry_run:
        print(f"Would update {total_updates} module versions in {total_modified} files")
    else:
        print(f"✅ Updated {total_updates} module versions in {total_modified} files")
    
    if total_modified == 0:
        print("ℹ️  No yaalalabs/ak-* modules found to update")


if __name__ == "__main__":
    main()
