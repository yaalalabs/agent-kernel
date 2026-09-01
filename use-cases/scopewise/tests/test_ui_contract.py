from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_home_explains_change_impact_with_one_constrained_next_action():
    script = (ROOT / "static" / "app.js").read_text()

    assert "function changeImpact()" in script
    assert "Your module changed" in script
    assert "impact.next_action" in script
    assert "sources:" in script and "scope:" in script and "review:" in script and "packs:" in script


def test_question_provenance_uses_student_language_and_collapsed_technical_details():
    script = (ROOT / "static" / "app.js").read_text()

    assert "function provenanceView(questionId)" in script
    assert "Compared by the local ScopeWise agent" in script
    assert "You still make the final decision" in script
    assert "Technical details for judges" in script
    assert "AgentService" in script
