from scopewise.candidates import select_candidates
from scopewise.models import Evidence, Objective


def objective(identifier, text, kind="required"):
    return Objective(
        id=identifier,
        text=text,
        kind=kind,
        approved=True,
        evidence=Evidence(document_id="syllabus", page=1, quote=text),
    )


def test_unrelated_database_topic_is_not_offered_by_lexical_fallback():
    selection = select_candidates(
        "Explain why indexing can improve query performance.",
        [objective("keys", "Explain primary keys and distinguish candidate keys.")],
    )

    assert selection.mode == "lexical"
    assert selection.objectives == []


def test_direct_explicit_exclusion_is_always_retained():
    exclusion = objective("bcnf", "BCNF proofs are explicitly excluded from this module.", "excluded")

    selection = select_candidates("Prove that every BCNF relation is in third normal form.", [exclusion])

    assert [item.id for item in selection.objectives] == ["bcnf"]
    assert selection.exclusion_ids == ["bcnf"]


def test_semantic_candidate_keeps_a_paraphrase_and_omits_a_weak_match():
    balanced = objective("balanced", "Evaluate rebalancing operations in ordered data structures.")
    unrelated = objective("sorting", "Compare stable sorting algorithms.")

    selection = select_candidates(
        "Explain how AVL rotations maintain tree height.",
        [balanced, unrelated],
        semantic_scores={"balanced": 0.71, "sorting": 0.20},
    )

    assert selection.mode == "semantic"
    assert [item.id for item in selection.objectives] == ["balanced"]
    assert selection.keyword_ids == []


def test_missing_semantic_scores_use_lexical_mode_without_raising():
    direct = objective("keys", "Explain primary keys and candidate keys.")

    selection = select_candidates("Explain candidate keys.", [direct], semantic_scores=None)

    assert selection.mode == "lexical"
    assert [item.id for item in selection.objectives] == ["keys"]
