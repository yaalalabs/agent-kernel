"""
Agent Kernel CLI — `ak` command.

Provides the `ak` top-level CLI entry point with subcommands.
Currently supports `ak skill` for managing agent skills.

Usage:
    ak skill list                      List all available skills
    ak skill info <name>               Show full details for a skill
    ak skill assistants                List supported coding assistants
    ak skill install                   Install all skills (default: copilot)
    ak skill install <name>            Install a specific skill
    ak skill install --assistant <a>   Install to a specific assistant's directory
    ak skill install --target <path>   Install to a custom directory
    ak skill update                    Re-install skills (overwrite existing)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agentkernel.skills import ASSISTANTS, DEFAULT_ASSISTANT, Skill


class AK:
    """Agent Kernel CLI."""

    def __init__(self) -> None:
        self._parser = self._build_parser()

    # ── Subcommand handlers ───────────────────────────────────────────

    @staticmethod
    def _resolve_target(args: argparse.Namespace) -> Path:
        """Resolve the target directory from --assistant or --target."""
        if hasattr(args, "target") and args.target:
            return Path(args.target)
        assistant_name = getattr(args, "assistant", DEFAULT_ASSISTANT)
        assistant = ASSISTANTS.get(assistant_name)
        if not assistant:
            print(f"Error: unknown assistant '{assistant_name}'.", file=sys.stderr)
            print(
                f"Supported: {', '.join(ASSISTANTS.keys())}", file=sys.stderr
            )
            sys.exit(1)
        return Path(assistant.skills_dir)

    def cmd_skill_list(self, args: argparse.Namespace) -> int:
        """Handle `ak skill list`."""
        skills = Skill.list_all()

        if not skills:
            print("No skills available.")
            return 1

        print(f"\nAgent Kernel Skills ({len(skills)} available):\n")

        max_name_len = max(len(s.name) for s in skills)

        for skill in skills:
            name = skill.name.ljust(max_name_len)
            desc = skill.description
            if len(desc) > 80:
                desc = desc[:77] + "..."
            print(f"  {name}  {desc}")

        print(f"\nInstall with: ak skill install [<name>] [--assistant <name>]")
        print(f"Details:      ak skill info <name>")
        return 0

    def cmd_skill_info(self, args: argparse.Namespace) -> int:
        """Handle `ak skill info <name>`."""
        skill = Skill.find(args.name)
        if skill is None:
            print(f"Error: skill '{args.name}' not found.", file=sys.stderr)
            print("Run 'ak skill list' to see available skills.", file=sys.stderr)
            return 1

        print(f"\n  {skill.name}")
        print(f"  {'─' * len(skill.name)}")
        print(f"  {skill.description}\n")
        return 0

    def cmd_skill_assistants(self, args: argparse.Namespace) -> int:
        """Handle `ak skill assistants`."""
        print("\nSupported coding assistants:\n")

        max_name = max(len(a.name) for a in ASSISTANTS.values())
        max_dir = max(len(a.skills_dir) for a in ASSISTANTS.values())

        for assistant in ASSISTANTS.values():
            name = assistant.name.ljust(max_name)
            sdir = assistant.skills_dir.ljust(max_dir)
            default = " (default)" if assistant.name == DEFAULT_ASSISTANT else ""
            print(f"  {name}  {sdir}  {assistant.description}{default}")

        print(f"\nUsage: ak skill install --assistant <name>")
        return 0

    def cmd_skill_install(self, args: argparse.Namespace) -> int:
        """Handle `ak skill install [<name>] [--assistant <name>] [--target <path>]`."""
        target = self._resolve_target(args)
        skill_name: str | None = args.name

        if skill_name:
            skill = Skill.find(skill_name)
            if skill is None:
                print(f"Error: skill '{skill_name}' not found.", file=sys.stderr)
                print(
                    f"Run 'ak skill list' to see available skills.", file=sys.stderr
                )
                return 1

            target.mkdir(parents=True, exist_ok=True)
            print(f"Installing skill '{skill_name}' to {target}/")
            success = skill.install(target, force=False)
            return 0 if success else 1
        else:
            skills = Skill.list_all()
            if not skills:
                print("No skills available to install.")
                return 1

            target.mkdir(parents=True, exist_ok=True)
            print(f"Installing {len(skills)} skills to {target}/\n")

            success_count = 0
            for skill in skills:
                if skill.install(target, force=False):
                    success_count += 1

            print(f"\n{success_count}/{len(skills)} skills installed.")
            return 0

    def cmd_skill_update(self, args: argparse.Namespace) -> int:
        """Handle `ak skill update [--assistant <name>] [--target <path>]`."""
        target = self._resolve_target(args)
        skills = Skill.list_all()

        if not skills:
            print("No skills available to update.")
            return 1

        target.mkdir(parents=True, exist_ok=True)
        print(f"Updating {len(skills)} skills in {target}/\n")

        success_count = 0
        for skill in skills:
            if skill.install(target, force=True):
                success_count += 1

        print(f"\n{success_count}/{len(skills)} skills updated.")
        return 0

    # ── Parser ────────────────────────────────────────────────────────

    @staticmethod
    def _build_parser() -> argparse.ArgumentParser:
        """Build the argument parser for the `ak` CLI."""
        parser = argparse.ArgumentParser(
            prog="ak",
            description="Agent Kernel CLI",
        )
        subparsers = parser.add_subparsers(dest="command", help="Available commands")

        # `ak skill` subcommand
        skill_parser = subparsers.add_parser("skill", help="Manage agent skills")
        skill_subparsers = skill_parser.add_subparsers(
            dest="skill_command", help="Skill commands"
        )

        # `ak skill list`
        skill_subparsers.add_parser("list", help="List all available skills")

        # `ak skill info <name>`
        info_parser = skill_subparsers.add_parser(
            "info", help="Show full details for a skill"
        )
        info_parser.add_argument(
            "name",
            help="Skill name to show details for",
        )

        # `ak skill assistants`
        skill_subparsers.add_parser(
            "assistants", help="List supported coding assistants"
        )

        # shared --assistant choices
        assistant_names = list(ASSISTANTS.keys())

        # `ak skill install`
        install_parser = skill_subparsers.add_parser(
            "install", help="Install skills to your project"
        )
        install_parser.add_argument(
            "name",
            nargs="?",
            default=None,
            help="Specific skill name to install (optional)",
        )
        install_group = install_parser.add_mutually_exclusive_group()
        install_group.add_argument(
            "--assistant",
            choices=assistant_names,
            default=DEFAULT_ASSISTANT,
            help=f"Coding assistant to install for (default: {DEFAULT_ASSISTANT})",
        )
        install_group.add_argument(
            "--target",
            default=None,
            help="Custom target directory (overrides --assistant)",
        )

        # `ak skill update`
        update_parser = skill_subparsers.add_parser(
            "update", help="Update (overwrite) installed skills"
        )
        update_group = update_parser.add_mutually_exclusive_group()
        update_group.add_argument(
            "--assistant",
            choices=assistant_names,
            default=DEFAULT_ASSISTANT,
            help=f"Coding assistant to update for (default: {DEFAULT_ASSISTANT})",
        )
        update_group.add_argument(
            "--target",
            default=None,
            help="Custom target directory (overrides --assistant)",
        )

        return parser

    # ── Entry point ───────────────────────────────────────────────────

    def run(self, argv: list[str] | None = None) -> None:
        """Parse arguments and dispatch to the appropriate subcommand."""
        args = self._parser.parse_args(argv)

        if args.command is None:
            self._parser.print_help()
            sys.exit(0)

        if args.command == "skill":
            if args.skill_command is None:
                self._parser.parse_args(["skill", "--help"])
                sys.exit(0)

            handlers = {
                "list": self.cmd_skill_list,
                "info": self.cmd_skill_info,
                "assistants": self.cmd_skill_assistants,
                "install": self.cmd_skill_install,
                "update": self.cmd_skill_update,
            }
            handler = handlers.get(args.skill_command)
            if handler:
                sys.exit(handler(args))
        else:
            self._parser.print_help()
            sys.exit(0)


def main() -> None:
    """Entry point for the `ak` CLI."""
    AK().run()


if __name__ == "__main__":
    main()
