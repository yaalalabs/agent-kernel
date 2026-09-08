"""Deterministic submission checks for ScopeWise judges and maintainers."""

import argparse
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from scopewise.store import Store

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_HEADINGS = (
    "Problem statement",
    "Solution overview",
    "Setup instructions",
    "How to run",
    "How Agent Kernel is used",
    "Verification",
)
REQUIRED_FILES = (
    "README.md",
    "SPEC.md",
    "AGENTS.md",
    "DEMO.md",
    "EVALUATION.md",
    "COMPETITION.md",
    "config.yaml",
    "scopewise/agents.py",
    "scopewise/app.py",
    "scopewise/service.py",
    "static/app.js",
    "static/index.html",
    "static/style.css",
)
LOCAL_MODELS = ("llama3.1:latest", "nomic-embed-text:latest")


@dataclass(frozen=True)
class Check:
    level: Literal["PASS", "WARN", "FAIL"]
    name: str
    detail: str


def _ollama_check() -> Check:
    try:
        result = subprocess.run(["ollama", "list"], cwd=ROOT, capture_output=True, text=True, timeout=15, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return Check("WARN", "Local Ollama models", "Ollama is unavailable; deterministic and manual workflows can still be reviewed.")
    if result.returncode:
        return Check("WARN", "Local Ollama models", "Ollama did not answer; run `ollama list` before demonstrating live model work.")
    missing = [model for model in LOCAL_MODELS if model not in result.stdout]
    if missing:
        return Check("WARN", "Local Ollama models", "One or more documented local models are not installed.")
    return Check("PASS", "Local Ollama models", "Documented local chat and embedding models are installed.")


def check(root: Path = ROOT) -> list[Check]:
    root = Path(root)
    checks = []
    missing_files = [relative for relative in REQUIRED_FILES if not (root / relative).is_file()]
    checks.append(
        Check(
            "FAIL" if missing_files else "PASS",
            "Required competition files",
            f"Missing: {', '.join(missing_files)}" if missing_files else "All required files exist.",
        )
    )

    readme = (root / "README.md").read_text() if (root / "README.md").is_file() else ""
    missing_headings = [heading for heading in REQUIRED_HEADINGS if f"## {heading}" not in readme]
    checks.append(
        Check(
            "FAIL" if missing_headings else "PASS",
            "README submission headings",
            f"Missing exact heading: {', '.join(missing_headings)}" if missing_headings else "All required headings are explicit.",
        )
    )

    config = (root / "config.yaml").read_text() if (root / "config.yaml").is_file() else ""
    config_ok = "type: in_memory" in config and "agent: scopewise_assistant" in config
    checks.append(
        Check(
            "PASS" if config_ok else "FAIL",
            "Agent Kernel configuration",
            "Session and Telegram agent configuration found." if config_ok else "Expected session and Telegram agent entries are missing.",
        )
    )

    try:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "judge-check.db"
            Store(database)
            with sqlite3.connect(database) as connection:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        checks.append(Check("PASS" if integrity == "ok" else "FAIL", "SQLite integrity", f"PRAGMA integrity_check: {integrity}"))
    except Exception as exc:
        checks.append(Check("FAIL", "SQLite integrity", f"Store initialization failed: {type(exc).__name__}"))

    checks.append(_ollama_check())
    return checks


def full_checks(root: Path = ROOT) -> list[Check]:
    commands = (
        ("Pytest", [".venv/bin/pytest", "-q"]),
        ("Ruff lint", [".venv/bin/ruff", "check", "."]),
        ("Ruff format", [".venv/bin/ruff", "format", "--check", "."]),
        ("JavaScript syntax", ["node", "--check", "static/app.js"]),
    )
    checks = []
    for name, command in commands:
        try:
            result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=180, check=False)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            checks.append(Check("FAIL", name, f"Could not run check: {type(exc).__name__}"))
            continue
        output = (result.stdout or result.stderr).strip().splitlines()
        detail = output[-1][:240] if output else f"exit code {result.returncode}"
        checks.append(Check("PASS" if result.returncode == 0 else "FAIL", name, detail))
    return checks


def main():
    parser = argparse.ArgumentParser(description="Check the ScopeWise competition package without exposing secrets.")
    parser.add_argument("--full", action="store_true", help="also run tests, lint, formatting, and JavaScript syntax")
    args = parser.parse_args()
    checks = [*check(ROOT), *(full_checks(ROOT) if args.full else [])]
    for item in checks:
        print(f"{item.level:4}  {item.name}: {item.detail}")
    raise SystemExit(1 if any(item.level == "FAIL" for item in checks) else 0)


if __name__ == "__main__":
    main()
