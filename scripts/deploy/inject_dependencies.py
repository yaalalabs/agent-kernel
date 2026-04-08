#!/usr/bin/env python3

import os
import re
import argparse
from pathlib import Path
from typing import List, Optional, Tuple


DEPLOYMENT_ROOTS = [
    'ak-deployment/ak-aws',
    'ak-deployment/ak-azure'
]

REGISTRY_TO_LOCAL_ROOTS = {
    'yaalalabs/ak-serverless/aws': ('ak-deployment/ak-aws/serverless', 'aws'),
    'yaalalabs/ak-containerized/aws': ('ak-deployment/ak-aws/containerized', 'aws'),
    'yaalalabs/ak-serverless/azurerm': ('ak-deployment/ak-azure/serverless', 'azurerm'),
    'yaalalabs/ak-containerized/azurerm': ('ak-deployment/ak-azure/containerized', 'azurerm'),
}

REGISTRY_PREFIX_RE = r'^(?:app\.terraform\.io/|registry\.terraform\.io/)?'

VERSION_MARKER = "AK_LOCAL_DEV_COMMENT"
PROVIDER_MARKER = "AK_PROVIDER"


# ---------- FILE DISCOVERY ----------

def _deployment_tf_files(workspace_root: Path) -> List[Path]:
    tf_files = []
    for root in DEPLOYMENT_ROOTS:
        root_path = workspace_root / root
        if root_path.exists():
            for tf_file in root_path.rglob('*.tf'):
                if '.terraform' not in tf_file.parts:
                    tf_files.append(tf_file)
    return sorted(tf_files)


# ---------- SOURCE LOCALIZATION ----------

def _localize_registry_source(source_value: str, file_path: Path, workspace_root: Path) -> Optional[Tuple[str, str]]:
    stripped = re.sub(REGISTRY_PREFIX_RE, '', source_value)

    if stripped in REGISTRY_TO_LOCAL_ROOTS:
        path, provider = REGISTRY_TO_LOCAL_ROOTS[stripped]
        target = workspace_root / path
        rel = os.path.relpath(target, file_path.parent)
        return rel, provider

    match = re.match(r'^yaalalabs/ak-common/(aws|azurerm|azure)//modules/([^"\s]+)$', stripped)
    if match:
        provider_raw = match.group(1)
        provider = 'azurerm' if provider_raw in {'azurerm', 'azure'} else 'aws'
        cloud_dir = 'ak-azure' if provider == 'azurerm' else 'ak-aws'
        target = workspace_root / f'ak-deployment/{cloud_dir}/common/modules/{match.group(2)}'
        rel = os.path.relpath(target, file_path.parent)
        return rel, provider

    return None


# ---------- SOURCE CHECKS ----------

def _is_yaalalabs_source(source_value: str) -> bool:
    stripped = re.sub(REGISTRY_PREFIX_RE, '', source_value)
    return stripped.startswith('yaalalabs/')


def _has_provider_marker(line: str) -> bool:
    return PROVIDER_MARKER in line


# ---------- RESTORE ----------

def _restore_registry_source(source_value: str, line: str, file_path: Path) -> Optional[str]:
    normalized = source_value.replace("\\", "/")

    try:
        resolved = (file_path.parent / normalized).resolve()
        resolved_normalized = str(resolved).replace("\\", "/")
    except Exception:
        return None

    provider_match = re.search(rf'{PROVIDER_MARKER}=(\w+)', line)
    provider = provider_match.group(1) if provider_match else None

    if not provider:
        return None

    if 'ak-deployment/ak-aws/serverless' in resolved_normalized:
        return 'yaalalabs/ak-serverless/aws'

    if 'ak-deployment/ak-aws/containerized' in resolved_normalized:
        return 'yaalalabs/ak-containerized/aws'

    if 'ak-deployment/ak-azure/serverless' in resolved_normalized:
        return 'yaalalabs/ak-serverless/azurerm'

    if 'ak-deployment/ak-azure/containerized' in resolved_normalized:
        return 'yaalalabs/ak-containerized/azurerm'

    match = re.search(r'common/modules/([^/"]+)', resolved_normalized)
    if match:
        return f'yaalalabs/ak-common/{provider}//modules/{match.group(1)}'

    return None


# ---------- CLEAN ----------

def _remove_provider_comment(line: str) -> str:
    return re.sub(rf'\s*#\s*{PROVIDER_MARKER}=\w+', '', line)


# ---------- MODULE BLOCK ----------

def _rewrite_module_block(block_lines, file_path, workspace_root, mode):
    rewritten = list(block_lines)
    changed = False
    is_managed_block = False

    # ---- SOURCE ----
    for i, line in enumerate(rewritten):
        m = re.match(r'^(\s*source\s*=\s*")([^"]+)(".*)$', line)
        if not m:
            continue

        source_val = m.group(2)

        # ---------- INJECT ----------
        if mode == 'inject':
            if _is_yaalalabs_source(source_val):
                result = _localize_registry_source(source_val, file_path, workspace_root)
                if result:
                    new_src, provider = result
                    rewritten[i] = f'{m.group(1)}{new_src}{m.group(3)} # {PROVIDER_MARKER}={provider}'
                    changed = True
                    is_managed_block = True

        # ---------- REVERT ----------
        else:
            if source_val.startswith('.') and _has_provider_marker(line):
                restored = _restore_registry_source(source_val, line, file_path)
                cleaned = _remove_provider_comment(line)

                if restored:
                    m2 = re.match(r'^(\s*source\s*=\s*")([^"]+)(".*)$', cleaned)
                    if m2:
                        rewritten[i] = f'{m2.group(1)}{restored}{m2.group(3)}'
                    else:
                        rewritten[i] = f'{m.group(1)}{restored}"'
                    changed = True
                    is_managed_block = True
                else:
                    if cleaned != line:
                        rewritten[i] = cleaned
                        changed = True

    # ---- VERSION ----
    if is_managed_block:
        for i, line in enumerate(rewritten):
            if mode == 'inject':
                vm = re.match(r'^(\s*)(version\s*=\s*"[^"]+")', line)
                if vm and not line.strip().startswith('#'):
                    rewritten[i] = f'{vm.group(1)}# {vm.group(2)} # {VERSION_MARKER}'
                    changed = True

            else:
                um = re.match(rf'^(\s*)#\s*(version\s*=\s*"[^"]+")\s*#\s*{VERSION_MARKER}.*$', line)
                if um:
                    rewritten[i] = f'{um.group(1)}{um.group(2)}'
                    changed = True

    return rewritten, changed


# ---------- FILE ----------

def _rewrite_tf_file(file_path: Path, workspace_root: Path, mode: str) -> bool:
    content = file_path.read_text()
    lines = content.split('\n')

    out = []
    i = 0

    while i < len(lines):
        line = lines[i]

        if re.match(r'^\s*module\s+"[^"]+"\s*{', line):
            block = [line]
            depth = line.count('{') - line.count('}')
            i += 1

            while i < len(lines) and depth > 0:
                block.append(lines[i])
                depth += lines[i].count('{') - lines[i].count('}')
                i += 1

            new_block, _ = _rewrite_module_block(block, file_path, workspace_root, mode)
            out.extend(new_block)

        else:
            out.append(line)
            i += 1

    new_content = '\n'.join(out)

    if new_content != content:
        file_path.write_text(new_content)
        return True

    return False


# ---------- ENTRY ----------

def inject_dependencies(root):
    root = Path(root)
    count = 0
    for tf in _deployment_tf_files(root):
        if _rewrite_tf_file(tf, root, 'inject'):
            print(f"✅ Injected -> {tf}")
            count += 1
    print(f"\n✨ Injected {count} files")


def revert_dependencies(root):
    root = Path(root)
    count = 0
    for tf in _deployment_tf_files(root):
        if _rewrite_tf_file(tf, root, 'revert'):
            print(f"✅ Reverted -> {tf}")
            count += 1
    print(f"\n✨ Reverted {count} files")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--revert', action='store_true')
    args = parser.parse_args()

    workspace_root = Path(__file__).parent.parent.parent

    if args.revert:
        print("🔄 Reverting...")
        revert_dependencies(workspace_root)
    else:
        print("📝 Injecting...")
        inject_dependencies(workspace_root)


if __name__ == "__main__":
    main()