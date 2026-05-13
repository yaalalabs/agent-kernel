#!/usr/bin/env python3

import argparse
import re
from pathlib import Path

SCRIPT_COMMENT_PREFIX = "# AK_AUTOCOMMENT:"
SCRIPT_BLOCK_START = "# AK_SCRIPT_BLOCK_START"
SCRIPT_BLOCK_END = "# AK_SCRIPT_BLOCK_END"

TARGET_FILES = [
    "terraform.tfvars",
    "main.tf",
    "variables.tf",
]


def generate_product_alias(existing_alias: str) -> str:
    parts = re.split(r"[-_]", existing_alias)

    if not parts:
        return existing_alias

    first = parts[0]

    shortened = [first]

    for part in parts[1:]:
        if part:
            shortened.append(part[0])

    return "-".join(shortened)


def comment_line(line: str) -> str:
    if line.lstrip().startswith("#"):
        return line

    return f"{SCRIPT_COMMENT_PREFIX} {line}"


def uncomment_script_line(line: str) -> str:
    if line.startswith(SCRIPT_COMMENT_PREFIX):
        return line[len(SCRIPT_COMMENT_PREFIX) + 1:]

    return line


def process_tfvars(tfvars_path: Path, region: str, openai_key: str):
    original = tfvars_path.read_text()

    if SCRIPT_BLOCK_START in original:
        print(f"[SKIP] Already processed: {tfvars_path}")
        return

    lines = original.splitlines(keepends=True)

    existing_alias = None

    for line in lines:
        match = re.match(r'\s*product_alias\s*=\s*"([^"]+)"', line)
        if match:
            existing_alias = match.group(1)
            break

    if not existing_alias:
        raise ValueError(f"Could not find product_alias in {tfvars_path}")

    new_product_alias = generate_product_alias(existing_alias)

    commented_original = "".join(comment_line(line) for line in lines)

    new_block = (
        f'{SCRIPT_BLOCK_START}\n'
        f'region        = "{region}"\n'
        f'product_alias = "{new_product_alias}"\n'
        f'env_alias     = "dev"\n'
        f'module_name   = "examples"\n'
        f'openai_api_key = "{openai_key}"\n'
        f'{SCRIPT_BLOCK_END}\n'
    )

    final_content = commented_original + "\n" + new_block

    tfvars_path.write_text(final_content)

    print(f"[UPDATED] {tfvars_path}")


def comment_matching_lines(file_path: Path, keywords: list[str]):
    original = file_path.read_text()

    if SCRIPT_COMMENT_PREFIX in original:
        print(f"[SKIP] Already processed: {file_path}")
        return

    lines = original.splitlines(keepends=True)

    updated_lines = []

    for line in lines:
        stripped = line.strip()

        should_comment = any(keyword in stripped for keyword in keywords)

        if should_comment and not stripped.startswith("#"):
            updated_lines.append(comment_line(line))
        else:
            updated_lines.append(line)

    file_path.write_text("".join(updated_lines))

    print(f"[UPDATED] {file_path}")


def comment_variable_blocks(file_path: Path, variable_names: list[str]):
    original = file_path.read_text()

    if SCRIPT_COMMENT_PREFIX in original:
        print(f"[SKIP] Already processed: {file_path}")
        return

    pattern = re.compile(
        r'(variable\s+"([^"]+)"\s*\{.*?\n\})',
        re.DOTALL,
    )

    updated_content = original

    matches = list(pattern.finditer(original))

    for match in reversed(matches):
        full_block = match.group(1)
        variable_name = match.group(2)

        if variable_name in variable_names:
            commented_block = "\n".join(
                comment_line(line)
                for line in full_block.splitlines()
            )

            updated_content = (
                updated_content[:match.start()]
                + commented_block
                + updated_content[match.end():]
            )

    file_path.write_text(updated_content)

    print(f"[UPDATED] {file_path}")


def revert_file(file_path: Path):
    content = file_path.read_text()

    lines = content.splitlines(keepends=True)

    reverted_lines = []

    inside_script_block = False

    for line in lines:
        stripped = line.strip()

        if stripped == SCRIPT_BLOCK_START:
            inside_script_block = True
            continue

        if stripped == SCRIPT_BLOCK_END:
            inside_script_block = False
            continue

        if inside_script_block:
            continue

        reverted_lines.append(uncomment_script_line(line))

    file_path.write_text("".join(reverted_lines))

    print(f"[REVERTED] {file_path}")


def find_deploy_dirs(root: Path):
    return list(root.rglob("deploy"))


def apply_changes(root: Path):
    region = input("Enter AWS region: ").strip()
    openai_key = input("Enter OpenAI API key: ").strip()

    deploy_dirs = find_deploy_dirs(root)

    if not deploy_dirs:
        print("No deploy directories found.")
        return

    for deploy_dir in deploy_dirs:
        print(f"\n[PROCESSING] {deploy_dir}")

        tfvars_path = deploy_dir / "terraform.tfvars"
        main_tf_path = deploy_dir / "main.tf"
        variables_tf_path = deploy_dir / "variables.tf"

        if tfvars_path.exists():
            process_tfvars(tfvars_path, region, openai_key)

        if main_tf_path.exists():
            comment_matching_lines(
                main_tf_path,
                ["vpc_id", "private_subnet_ids"],
            )

        if variables_tf_path.exists():
            comment_variable_blocks(
                variables_tf_path,
                ["vpc_id", "private_subnet_ids"],
            )


def revert_changes(root: Path):
    deploy_dirs = find_deploy_dirs(root)

    if not deploy_dirs:
        print("No deploy directories found.")
        return

    for deploy_dir in deploy_dirs:
        print(f"\n[REVERTING] {deploy_dir}")

        for filename in TARGET_FILES:
            path = deploy_dir / filename

            if path.exists():
                revert_file(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--revert",
        action="store_true",
        help="Revert changes made by this script",
    )

    args = parser.parse_args()

    root = Path.cwd()

    if args.revert:
        revert_changes(root)
    else:
        apply_changes(root)


if __name__ == "__main__":
    main()