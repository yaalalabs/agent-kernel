# Agent Kernel Skills
# This module contains bundled agent skills that can be installed
# into user projects via the `ak skill` CLI command.

from agentkernel.skills.skills import ASSISTANTS, DEFAULT_ASSISTANT, Assistant, Skill

__all__ = ["Assistant", "ASSISTANTS", "DEFAULT_ASSISTANT", "Skill"]
