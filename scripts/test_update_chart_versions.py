#!/usr/bin/env python3
"""Tests for update_chart_versions.py script."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from update_chart_versions import SEMVER_PATTERN, find_files, update_chart_versions

CHART = "oci://ghcr.io/yaalalabs/charts/agent-kernel"


def _write_temp(content: str, suffix: str) -> Path:
    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
        f.write(content)
        f.flush()
        return Path(f.name)


def test_update_readme_install_command():
    """A README install command gets its pinned version replaced and nothing else."""
    content = f"""```bash
helm install ak {CHART} --version 0.9.0 \\
  -f ../../../ak-deployment/ak-k8s/chart/values-dev.yaml -f ak-values.yaml
```
"""
    expected = f"""```bash
helm install ak {CHART} --version 0.9.1 \\
  -f ../../../ak-deployment/ak-k8s/chart/values-dev.yaml -f ak-values.yaml
```
"""
    temp_path = _write_temp(content, ".md")
    try:
        was_modified, num_updates = update_chart_versions(temp_path, "0.9.1")

        assert was_modified, "File should be modified"
        assert num_updates == 1, f"Expected 1 update, got {num_updates}"
        assert temp_path.read_text() == expected, f"Content mismatch:\n{temp_path.read_text()}"
        print("✅ test_update_readme_install_command passed")
    finally:
        temp_path.unlink()


def test_update_values_comment_with_prerelease():
    """A values-file comment keeps its comment marker; hyphenated prereleases are valid targets."""
    content = f"""# Install:
#
#   helm install ak {CHART} --version 0.9.0 \\
#     -f ../../../ak-deployment/ak-k8s/chart/values-dev.yaml -f sandbox-values.yaml

image:
  tag: dev
"""
    temp_path = _write_temp(content, ".yaml")
    try:
        was_modified, num_updates = update_chart_versions(temp_path, "1.0.0-a1")

        assert was_modified, "File should be modified"
        assert num_updates == 1, f"Expected 1 update, got {num_updates}"
        result = temp_path.read_text()
        assert f"#   helm install ak {CHART} --version 1.0.0-a1 \\" in result
        assert "image:\n  tag: dev" in result, "unrelated YAML must be untouched"
        print("✅ test_update_values_comment_with_prerelease passed")
    finally:
        temp_path.unlink()


def test_update_multiple_references():
    """Every reference in a file is pinned, and the count reflects all of them."""
    content = f"""helm install ak {CHART} --version 0.9.0 -f a.yaml
microk8s helm install ak {CHART} --version 0.9.0 \\
  -f b.yaml
helm upgrade --install ak {CHART} --version 0.8.1 --set x=y
"""
    temp_path = _write_temp(content, ".md")
    try:
        was_modified, num_updates = update_chart_versions(temp_path, "0.9.1")

        assert was_modified, "File should be modified"
        assert num_updates == 3, f"Expected 3 updates, got {num_updates}"
        result = temp_path.read_text()
        assert result.count("--version 0.9.1") == 3
        assert "0.9.0" not in result and "0.8.1" not in result
        print("✅ test_update_multiple_references passed")
    finally:
        temp_path.unlink()


def test_no_changes_when_already_pinned():
    """References already at the target version are not rewritten or counted."""
    content = f"helm install ak {CHART} --version 0.9.1 -f a.yaml\n"
    temp_path = _write_temp(content, ".md")
    try:
        was_modified, num_updates = update_chart_versions(temp_path, "0.9.1")

        assert not was_modified, "File should not be modified"
        assert num_updates == 0, f"Expected 0 updates, got {num_updates}"
        assert temp_path.read_text() == content
        print("✅ test_no_changes_when_already_pinned passed")
    finally:
        temp_path.unlink()


def test_skips_local_paths_other_charts_and_placeholders():
    """Local chart installs, third-party charts, and <version> placeholders are left alone."""
    content = f"""helm dependency build ../../../ak-deployment/ak-k8s/chart
helm install ak ../../../ak-deployment/ak-k8s/chart -f values-dev.yaml
helm install monitoring oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack --version 90.0.0
helm pull {CHART} --version <version>
helm install ak oci://registry.example.internal/charts/agent-kernel --version <version>
"""
    temp_path = _write_temp(content, ".md")
    try:
        was_modified, num_updates = update_chart_versions(temp_path, "0.9.1")

        assert not was_modified, "File should not be modified"
        assert num_updates == 0, f"Expected 0 updates, got {num_updates}"
        assert temp_path.read_text() == content
        print("✅ test_skips_local_paths_other_charts_and_placeholders passed")
    finally:
        temp_path.unlink()


def test_update_deploy_script_pin():
    """A deploy script's CHART_VERSION variable is repinned when the script names the chart."""
    content = f"""#!/bin/bash
CHART_REF="{CHART}"
# The published chart version; scripts/update_chart_versions.py pins it to each release.
CHART_VERSION="0.9.0"
LOCAL_CHART="$SCRIPT_DIR/../../../../ak-deployment/ak-k8s/chart"
"""
    temp_path = _write_temp(content, ".sh")
    try:
        was_modified, num_updates = update_chart_versions(temp_path, "1.0.0-b2")

        assert was_modified, "File should be modified"
        assert num_updates == 1, f"Expected 1 update, got {num_updates}"
        result = temp_path.read_text()
        assert 'CHART_VERSION="1.0.0-b2"\n' in result
        assert f'CHART_REF="{CHART}"' in result, "the reference line must be untouched"
        assert "ak-deployment/ak-k8s/chart" in result
        print("✅ test_update_deploy_script_pin passed")
    finally:
        temp_path.unlink()


def test_shell_pin_needs_the_chart_reference():
    """A CHART_VERSION variable in a script that never names the chart is not ours to touch."""
    content = 'CHART_VERSION="0.9.0"\nhelm install other ./some-other-chart\n'
    temp_path = _write_temp(content, ".sh")
    try:
        was_modified, num_updates = update_chart_versions(temp_path, "0.9.1")

        assert not was_modified and num_updates == 0
        assert temp_path.read_text() == content
        print("✅ test_shell_pin_needs_the_chart_reference passed")
    finally:
        temp_path.unlink()


def test_find_files_globs_and_excludes():
    """Only .md/.yaml/.yml/.sh files are scanned, and excluded path segments are skipped."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        wanted = [
            root / "k8s" / "README.md",
            root / "k8s" / "values.yaml",
            root / "x" / "c.yml",
            root / "k8s" / "deploy" / "deploy.sh",
        ]
        unwanted = [root / ".venv" / "lib" / "README.md", root / "k8s" / "app.py", root / "k8s" / "uv.lock"]
        for path in wanted + unwanted:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("")

        found = find_files([str(root)])

        assert sorted(found) == sorted(wanted), f"Unexpected file set: {found}"
        print("✅ test_find_files_globs_and_excludes passed")


def test_find_files_accepts_single_file():
    """An entry naming a file is scanned as given; foreign suffixes and excluded path segments still apply."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        readme = root / "README.md"
        readme.write_text("")
        (root / "pyproject.toml").write_text("")
        excluded = root / ".venv" / "README.md"
        excluded.parent.mkdir()
        excluded.write_text("")

        found = find_files([str(readme), str(root / "pyproject.toml"), str(root / "missing.md"), str(excluded)])

        assert found == [readme], f"Unexpected file set: {found}"
        print("✅ test_find_files_accepts_single_file passed")


def test_semver_validation():
    """Tag-form versions are accepted; PEP 440 prereleases and v-prefixed tags are not."""
    for version in ("0.9.1", "1.0.0-a1", "1.0.0-b2", "2.0.0-rc.1"):
        assert SEMVER_PATTERN.match(version), f"{version} should be accepted"
    for version in ("1.0.0a1", "v1.0.0", "1.0", "<version>"):
        assert not SEMVER_PATTERN.match(version), f"{version} should be rejected"
    print("✅ test_semver_validation passed")


if __name__ == "__main__":
    print("Running tests for update_chart_versions.py...\n")

    test_update_readme_install_command()
    test_update_values_comment_with_prerelease()
    test_update_multiple_references()
    test_no_changes_when_already_pinned()
    test_skips_local_paths_other_charts_and_placeholders()
    test_update_deploy_script_pin()
    test_shell_pin_needs_the_chart_reference()
    test_find_files_globs_and_excludes()
    test_find_files_accepts_single_file()
    test_semver_validation()

    print("\n✅ All tests passed!")
