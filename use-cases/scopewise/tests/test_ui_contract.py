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


def test_guided_setup_requires_only_three_material_uploads_before_preparing_review():
    script = (ROOT / "static" / "app.js").read_text()

    assert "Start from my material" in script
    assert "Upload and prepare" in script
    assert 'data-form="guided-upload"' in script
    assert 'name="syllabus"' in script
    assert 'name="guidance"' in script
    assert 'name="paper"' in script
    assert "Upload and prepare my review" in script
    assert "Preparing your scope, questions, and comparison" in script
    assert "human review required" in script


def test_suitable_recommendations_can_be_confirmed_and_packed_once():
    script = (ROOT / "static" / "app.js").read_text()

    assert "Make recommended pack" in script
    assert "Make pack" in script
    assert "matches/review-suitable" in script
    assert "More review options" in script


def test_pack_size_is_explained_with_available_counts():
    script = (ROOT / "static" / "app.js").read_text()

    assert "available unique" in script
    assert "Questions wanted" in script
    assert "from uploaded papers" in script
    assert "not confirmed suitable" in script


def test_pack_can_fill_missing_slots_with_selected_generation_difficulty():
    script = (ROOT / "static" / "app.js").read_text()

    assert "Generate missing questions from confirmed syllabus" in script
    assert '<option value="easy">Easy</option>' in script
    assert '<option value="medium" selected>Medium</option>' in script
    assert '<option value="difficult">Difficult</option>' in script
    assert "/packs/generate" in script
    assert "AI-generated practice" in script


def test_primary_workflow_hides_optional_detail_until_requested():
    script = (ROOT / "static" / "app.js").read_text()

    assert "More options" in script
    assert "Advanced source tools" in script
    assert "Inspect or correct individual questions" in script
    assert "Earlier packs" in script
    assert 'name="confirmed"' not in script


def test_failed_preparation_has_one_click_automatic_retry():
    script = (ROOT / "static" / "app.js").read_text()

    assert "Retry automatic preparation" in script
    assert "retry-review" in script


def test_typography_and_controls_meet_readability_floor():
    styles = (ROOT / "static" / "style.css").read_text()

    assert ":root{font-size:16px}" in styles
    assert "min-height:44px" in styles
