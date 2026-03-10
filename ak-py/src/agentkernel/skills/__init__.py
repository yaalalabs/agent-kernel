# Agent Kernel Skills
# This module contains bundled agent skills that can be installed
# into user projects via the `ak skill` CLI command.

from agentkernel.skills.skills import ASSISTANTS, DEFAULT_ASSISTANT, Assistant, Skill

__all__ = ["Assistant", "ASSISTANTS", "DEFAULT_ASSISTANT", "Skill", "get_skills_dir", "list_skills"]


def get_skills_dir():
    """Return the path to the bundled skills directory."""
    return Skill._get_skills_dir()


def list_skills() -> list[dict[str, str]]:
    """List all available skills with their name and description."""
    return [s.to_dict() for s in Skill.list_all()]
