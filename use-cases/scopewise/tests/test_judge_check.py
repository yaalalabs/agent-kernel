from types import SimpleNamespace

from scripts import judge_check
from scripts.evaluate_model import ADVERSARIAL


def project(tmp_path):
    for relative in judge_check.REQUIRED_FILES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder")
    (tmp_path / "README.md").write_text("\n".join(f"## {heading}" for heading in judge_check.REQUIRED_HEADINGS))
    (tmp_path / "config.yaml").write_text("session:\n  type: in_memory\ntelegram:\n  agent: scopewise_assistant\n")
    return tmp_path


def available_ollama(*_args, **_kwargs):
    return SimpleNamespace(returncode=0, stdout="llama3.1:latest\nnomic-embed-text:latest\n", stderr="")


def test_minimal_competition_project_has_no_hard_failures(tmp_path, monkeypatch):
    root = project(tmp_path)
    monkeypatch.setattr(judge_check.subprocess, "run", available_ollama)

    checks = judge_check.check(root)

    assert not [item for item in checks if item.level == "FAIL"]


def test_missing_required_readme_heading_is_a_failure(tmp_path, monkeypatch):
    root = project(tmp_path)
    (root / "README.md").write_text("## Problem statement\n")
    monkeypatch.setattr(judge_check.subprocess, "run", available_ollama)

    failures = [item for item in judge_check.check(root) if item.level == "FAIL"]

    assert any("How to run" in item.detail for item in failures)


def test_missing_ollama_is_a_warning_not_a_failure(tmp_path, monkeypatch):
    root = project(tmp_path)

    def missing(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(judge_check.subprocess, "run", missing)

    ollama = next(item for item in judge_check.check(root) if item.name == "Local Ollama models")

    assert ollama.level == "WARN"


def test_development_regression_includes_depth_exclusion_and_prerequisite_traps():
    assert ADVERSARIAL == [
        ("Explain why indexing improves query performance.", "uncertain"),
        ("Prove that every BCNF relation is in third normal form.", "beyond_scope"),
        ("Distinguish a primary key from a candidate key.", "aligned"),
        ("Explain B+ tree leaf-node splitting.", "uncertain"),
        ("Decompose the supplied relation into third normal form.", "aligned"),
        ("State the definition of third normal form.", "partial"),
        ("Write a join combining customer and order tables.", "aligned"),
        ("Use relational division to find students taking every course.", "uncertain"),
    ]
