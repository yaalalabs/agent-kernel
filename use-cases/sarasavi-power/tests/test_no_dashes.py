"""No em/en dash may reach a user, from any send path.

Most replies pass through WhatsAppFormatHook, which strips dashes. But several
paths send text directly and never touch a hook: the post-call recap, the
busy-lines message, the media acknowledgement and the language prompt. Each of
those shipped with a dash at some point, so the rule is enforced by scanning the
modules rather than by listing constants that someone must remember to add.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Modules whose string literals either reach the user or steer the model. Prompts
# are included deliberately: a prompt that uses dashes teaches the model to use them.
SCANNED = [
    "hooks.py",
    "agent.py",
    "voice/summary.py",
    "voice/call_manager.py",
    "voice/live_agent.py",
    "whatsapp_ext/handler.py",
    "whatsapp_ext/interactive.py",
    "whatsapp_ext/media.py",
]

DASHES = ("\u2014", "\u2013")


def _exempt_strings(tree: ast.Module) -> set[str]:
    """Literals that are not prose: docstrings, and regexes that match dashes.

    The dash-stripping patterns in hooks.py necessarily contain the characters
    they remove.
    """
    exempt = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                exempt.add(doc)
        if isinstance(node, ast.Call):
            func = node.func
            is_re_compile = (isinstance(func, ast.Attribute) and func.attr == "compile") or (
                isinstance(func, ast.Name) and func.id == "compile"
            )
            if is_re_compile:
                exempt.update(
                    arg.value for arg in ast.walk(node) if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                )
    return exempt


def _offending_strings(path: pathlib.Path) -> list[str]:
    """String literals containing a dash, ignoring docstrings, comments and regexes."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    exempt = _exempt_strings(tree)

    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value not in exempt
        and any(dash in node.value for dash in DASHES)
    ]


@pytest.mark.parametrize("module", SCANNED)
def test_module_has_no_dashes_in_user_facing_or_prompt_strings(module: str) -> None:
    offenders = _offending_strings(ROOT / module)

    assert not offenders, f"{module} has dashes in: {[o[:70] for o in offenders]}"
