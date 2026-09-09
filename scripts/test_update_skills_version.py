#!/usr/bin/env python3
"""Tests for update_skills_version.py script."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from update_skills_version import discover_current_versions, update_skills_versions


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_update_skill_metadata_and_docs_versions() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        skills_dir = Path(tmp_dir) / "skills"

        skill_md = skills_dir / "ak-cloud-deploy" / "SKILL.md"
        eval_json = skills_dir / "ak-cloud-deploy" / "evals" / "evals.json"

        _write(
            skill_md,
            """---
name: ak-cloud-deploy
metadata:
  version: "0.4.0"
---

Use current module version (`0.4.0`) unless user requests another.

```toml
dependencies = ["agentkernel[openai,api]>=0.4.0", "black>=23.0.0"]
```

```hcl
module "serverless_agents" {
  version = "0.4.0"
}
```
""",
        )

        _write(
            eval_json,
            """{
  "skill": "ak-cloud-deploy",
  "version": "0.4.0",
  "evals": [
    {
      "expected_outputs": ["agentkernel[", ">=0.4.0"]
    }
  ]
}
""",
        )

        modified_files, replacements = update_skills_versions(skills_dir, "0.5.1")

        assert modified_files == 2
        assert replacements >= 5

        updated_skill = skill_md.read_text(encoding="utf-8")
        updated_evals = eval_json.read_text(encoding="utf-8")

        assert 'version: "0.5.1"' in updated_skill
        assert "Use current module version (`0.5.1`)" in updated_skill
        assert 'agentkernel[openai,api]>=0.5.1' in updated_skill
        assert 'version = "0.5.1"' in updated_skill
        assert 'black>=23.0.0' in updated_skill

        assert '"version": "0.5.1"' in updated_evals
        assert '">=0.5.1"' in updated_evals


def test_no_changes_when_target_version_is_already_set() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        skills_dir = Path(tmp_dir) / "skills"
        skill_md = skills_dir / "ak-init" / "SKILL.md"

        _write(
            skill_md,
            """---
name: ak-init
metadata:
  version: "0.4.0"
---

dependencies = ["agentkernel[openai]>=0.4.0"]
""",
        )

        assert discover_current_versions(skills_dir) == {"0.4.0"}

        modified_files, replacements = update_skills_versions(skills_dir, "0.4.0")
        assert modified_files == 0
        assert replacements == 0
