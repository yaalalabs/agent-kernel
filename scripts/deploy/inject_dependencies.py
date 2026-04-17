#!/usr/bin/env python3

import os
import re
import argparse
import yaml
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Set


DEPLOYMENT_ROOTS = [
    'ak-deployment/ak-aws',
    'ak-deployment/ak-azure',
    'examples'
]

BACKEND_TEMPLATES = {
    'aws': 'backend.tf.aws.template',
    'azure': 'backend.tf.azure.template',
}

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

def get_cloud(project_type: str) -> str:
    if project_type.startswith('aws'):
        return 'aws'
    elif project_type.startswith('azure'):
        return 'azure'
    else:
        raise ValueError(f"Unknown project type: {project_type}")

def load_yaml(path: Path) -> Dict:
    with open(path, 'r') as f:
        return yaml.safe_load(f)


def get_projects(config: Dict) -> Set[Tuple[str, str, str]]:
    projects = set()

    if 'deployment_base' in config:
        for project in config['deployment_base']:
            t = project.get('type', '')
            if t in ['aws-serverless', 'aws-containerized', 'azure-serverless', 'azure-containerized']:
                path = project.get('path', '')
                deploy_dir = project.get('deploy_dir', 'deploy')
                if path:
                    projects.add((path, deploy_dir, t))

    for schedule in ['nightly', 'weekly']:
        if schedule in config and 'tests' in config[schedule]:
            for test in config[schedule]['tests']:
                t = test.get('type', '')
                if t in ['aws-serverless', 'aws-containerized', 'azure-serverless', 'azure-containerized']:
                    path = test.get('path', '')
                    deploy_dir = test.get('deploy_dir', 'deploy')
                    if path:
                        projects.add((path, deploy_dir, t))

    return projects

def generate_backend_tf(template: str, project_path: str, project_type: str, state_config: Dict) -> str:
    cloud = get_cloud(project_type)
    cfg = state_config[cloud]['state']

    state_key = f"{project_path}/terraform.tfstate"

    content = template.replace('{state_key}', state_key)

    for key, value in cfg.items():
        content = content.replace(f'{{{key}}}', value)

    return content

def inject_backend_files(workspace_root: Path,
                         templates: Dict[str, str],
                         state_config: Dict,
                         projects: Set[Tuple[str, str, str]]):

    count = 0

    for project_path, deploy_dir, project_type in sorted(projects):
        deploy_path = workspace_root / project_path / deploy_dir

        if not deploy_path.exists():
            print(f"⚠️  Missing deploy dir: {deploy_path}")
            continue

        cloud = get_cloud(project_type)

        backend_path = deploy_path / "backend.tf"
        content = generate_backend_tf(
            templates[cloud],
            project_path,
            project_type,
            state_config
        )

        backend_path.write_text(content)

        print(f"✅ backend.tf -> {backend_path}")
        count += 1

    print(f"\n✨ Injected backend.tf into {count} projects")

def remove_backend_files(
    workspace_root: Path,
    projects: Set[Tuple[str, str, str]]
) -> None:
    """
    Remove backend.tf files from all project deploy directories.

    Args:
        workspace_root: Root directory of the workspace
        projects: Set of project tuples (path, deploy_dir, type)
    """
    removed_count = 0
    skipped_count = 0

    for project_path, deploy_dir, _ in sorted(projects):
        deploy_path = workspace_root / project_path / deploy_dir
        backend_path = deploy_path / "backend.tf"

        if not deploy_path.exists():
            print(f"⚠️  Missing deploy dir: {deploy_path}")
            continue

        if backend_path.exists():
            try:
                backend_path.unlink()
                print(f"🗑️  Removed backend.tf -> {backend_path}")
                removed_count += 1
            except Exception as e:
                print(f"❌ Failed to remove {backend_path}: {e}")
        else:
            skipped_count += 1

    print(f"\n✨ Removed backend.tf from {removed_count} projects")
    if skipped_count:
        print(f"ℹ️  Skipped {skipped_count} projects (no backend.tf found)")
        
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
    print("🔧 AK Dependency Injector\n")
    parser = argparse.ArgumentParser()
    parser.add_argument('--revert', action='store_true')
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    workspace_root = script_dir.parent.parent

    config_path = workspace_root / '.github' / 'integration-test-config.yaml'
    state_config_path = script_dir / 'state-config.yaml'

    if not config_path.exists():
        print(f"❌ Missing config: {config_path}")
        return 1

    if not state_config_path.exists():
        print(f"❌ Missing state config: {state_config_path}")
        return 1

    config = load_yaml(config_path)
    state_config = load_yaml(state_config_path)

    # Load templates
    templates = {}
    for cloud, filename in BACKEND_TEMPLATES.items():
        path = script_dir / filename
        if not path.exists():
            print(f"❌ Missing template: {path}")
            return 1
        templates[cloud] = path.read_text()

    projects = get_projects(config)
    print(f"🔍 Found {len(projects)} projects")

    if args.revert:
        print("🔄 Removing backend.tf...")
        remove_backend_files(workspace_root, projects)
        
        print("🔄 Reverting modules...")
        revert_dependencies(workspace_root)
    else:
        print("📝 Injecting backend.tf...")
        inject_backend_files(workspace_root, templates, state_config, projects)

        print("\n📝 Rewriting module sources...")
        inject_dependencies(workspace_root)

if __name__ == "__main__":
    main()