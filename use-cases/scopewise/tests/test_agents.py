import pytest

from scopewise.agents import validate_analysis, validate_extraction
from scopewise.models import Analysis, Evidence, Extraction, Match, Objective


def test_extraction_cannot_approve_itself_or_cite_another_document():
    document = {"id": "s", "role": "syllabus", "pages": ["Explain primary keys and distinguish candidate keys."]}
    result = Extraction(
        objectives=[
            Objective(id="model-chosen", text="Explain keys", approved=True, evidence=Evidence(document_id="s", page=1, quote="Explain primary keys"))
        ]
    )
    cleaned = validate_extraction(result, document)
    assert cleaned.objectives[0].approved is False
    assert cleaned.objectives[0].id != "model-chosen"
    result.objectives[0].evidence.document_id = "other-user-file"
    with pytest.raises(ValueError):
        validate_extraction(result, document)


def test_analysis_requires_one_result_per_requested_question():
    from test_core import fixtures

    docs, objectives, questions = fixtures()
    result = Analysis(matches=[Match(question_id="q1", reason="Uncertain")])
    with pytest.raises(ValueError, match="every"):
        validate_analysis(result, docs, objectives, questions)


def test_model_cannot_review_its_own_judgment():
    from test_core import fixtures

    docs, objectives, questions = fixtures()
    result = Analysis(matches=[Match(question_id=q.id, reason="Uncertain", reviewed=True) for q in questions])
    assert all(not m.reviewed for m in validate_analysis(result, docs, objectives, questions).matches)


def test_decision_uses_only_supplied_references_and_copies_source_evidence():
    from test_core import fixtures

    from scopewise.agents import decision_match
    from scopewise.models import Decision

    docs, objectives, questions = fixtures()
    decision = Decision(
        objective_keys=["O1"],
        scope_status="aligned",
        reason="Same concept and depth",
        assessment_status="unknown",
        assessment_reason="No evidence",
        guidance=[],
    )
    match = decision_match(decision, questions[0], {"O1": objectives[0]}, {})
    assert match.evidence == [objectives[0].evidence]
    assert match.question_id == "q1"
    assert not match.reviewed
    decision.objective_keys = ["O999"]
    match = decision_match(decision, questions[0], {"O1": objectives[0]}, {})
    assert match.scope_status == "uncertain"
    assert match.objective_ids == []
    assert match.evidence == []
    assert "discarded" in match.reason.lower()


def test_unknown_guidance_reference_is_discarded_without_losing_the_question():
    from test_core import fixtures

    from scopewise.agents import decision_match
    from scopewise.models import Decision, GuidanceQuote

    docs, objectives, questions = fixtures()
    decision = Decision(
        objective_keys=["O1"],
        scope_status="aligned",
        reason="Same concept and depth",
        assessment_status="matches_guidance",
        assessment_reason="The expected format is the same.",
        guidance=[GuidanceQuote(source="G999", page=1, quote="Use a worked example in every answer.")],
    )
    match = decision_match(decision, questions[0], {"O1": objectives[0]}, {"G1": docs[-1]})
    assert match.scope_status == "aligned"
    assert match.assessment_status == "unknown"
    assert match.assessment_evidence == []
    assert "discarded" in match.assessment_reason.lower()
