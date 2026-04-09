"""Agent Kernel Skills — Skill class for discovering and installing skills."""

from __future__ import annotations

import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

# ── Assistant registry ────────────────────────────────────────────────


@dataclass(frozen=True)
class Assistant:
    """Describes where a coding assistant expects skills to be installed."""

    name: str
    skills_dir: str
    description: str


# Canonical registry of supported coding assistants and their skill directories.
ASSISTANTS: dict[str, Assistant] = {
    "copilot": Assistant(
        name="copilot",
        skills_dir=".agents/skills",
        description="GitHub Copilot (VS Code / JetBrains)",
    ),
    "claude": Assistant(
        name="claude",
        skills_dir=".claude/commands",
        description="Claude Code (Anthropic)",
    ),
    "cursor": Assistant(
        name="cursor",
        skills_dir=".cursor/rules",
        description="Cursor IDE",
    ),
    "windsurf": Assistant(
        name="windsurf",
        skills_dir=".windsurf/rules",
        description="Windsurf (Codeium)",
    ),
    "codex": Assistant(
        name="codex",
        skills_dir=".codex/skills",
        description="Codex CLI (OpenAI)",
    ),
    "aider": Assistant(
        name="aider",
        skills_dir=".aider/skills",
        description="Aider",
    ),
}

DEFAULT_ASSISTANT = "copilot"


class Skill:
    """Represents and manages bundled agent skills."""

    def __init__(self, name: str, description: str = "", source_dir: Path | None = None) -> None:
        self.name = name
        self.description = description
        self._source_dir = source_dir or (self._get_skills_dir() / name)

    # ── Class-level discovery ─────────────────────────────────────────

    @staticmethod
    def _get_skills_dir() -> Path:
        """Return the path to the bundled skills directory."""
        return Path(__file__).parent

    @classmethod
    def list_all(cls) -> list[Skill]:
        """Return all available bundled skills."""
        skills_dir = cls._get_skills_dir()
        skills: list[Skill] = []

        if not skills_dir.exists():
            return skills

        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name.startswith("_"):
                continue

            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            name, description = cls._parse_frontmatter(skill_md)
            skills.append(cls(name=name, description=description, source_dir=skill_dir))

        return skills

    @classmethod
    def find(cls, name: str) -> Skill | None:
        """Find a skill by name. Returns None if not found."""
        skill_dir = cls._get_skills_dir() / name
        if not skill_dir.is_dir():
            return None

        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            return None

        parsed_name, description = cls._parse_frontmatter(skill_md)
        return cls(name=parsed_name, description=description, source_dir=skill_dir)

    # ── Instance operations ───────────────────────────────────────────

    @property
    def exists(self) -> bool:
        """Check whether this skill's source directory exists."""
        return self._source_dir.exists() and (self._source_dir / "SKILL.md").exists()

    def install(self, target_dir: Path, *, force: bool = False) -> bool:
        """Install this skill to the target directory. Returns True on success."""
        if not self._source_dir.exists():
            print(f"  Error: skill '{self.name}' not found", file=sys.stderr)
            return False

        skill_md = self._source_dir / "SKILL.md"
        if not skill_md.exists():
            print(f"  Error: skill '{self.name}' has no SKILL.md", file=sys.stderr)
            return False

        dest_dir = target_dir / self.name

        if dest_dir.exists() and not force:
            print(f"  Skipped: {self.name} (already exists, use 'update' to overwrite)")
            return True

        if dest_dir.exists():
            shutil.rmtree(dest_dir)

        shutil.copytree(
            self._source_dir,
            dest_dir,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        print(f"  Installed: {self.name}")
        return True

    def to_dict(self) -> dict[str, str]:
        """Return a dict representation with name and description."""
        return {"name": self.name, "description": self.description}

    def __repr__(self) -> str:
        return f"Skill(name={self.name!r})"

    # ── Private helpers ───────────────────────────────────────────────

    @staticmethod
    def _parse_frontmatter(skill_md: Path) -> tuple[str, str]:
        """Parse name and description from SKILL.md YAML frontmatter.

        Returns:
            A (name, description) tuple.  The name from frontmatter is
            validated against the directory name; a mismatch triggers a
            warning and the directory name is used.
        """
        content = skill_md.read_text(encoding="utf-8")
        dir_name = skill_md.parent.name
        name = dir_name
        description = ""

        frontmatter_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if not frontmatter_match:
            return name, description

        frontmatter = frontmatter_match.group(1)

        # Parse name from frontmatter
        name_match = re.search(r'^name:\s*["\']?(.*?)["\']?\s*$', frontmatter, re.MULTILINE)
        if name_match:
            fm_name = name_match.group(1).strip()
            if fm_name and fm_name != dir_name:
                print(
                    f"  Warning: skill '{dir_name}' has mismatched frontmatter " f"name '{fm_name}'; using directory name",
                    file=sys.stderr,
                )
            elif fm_name:
                name = fm_name

        # Multi-line description (YAML block scalar)
        desc_match = re.search(r"description:\s*>?\s*\n((?:\s+.*\n)*)", frontmatter)
        if desc_match:
            description = " ".join(line.strip() for line in desc_match.group(1).strip().splitlines())
        else:
            # Single-line description
            desc_match = re.search(r'description:\s*["\']?(.*?)["\']?\s*$', frontmatter, re.MULTILINE)
            if desc_match:
                description = desc_match.group(1).strip()

        return name, description
