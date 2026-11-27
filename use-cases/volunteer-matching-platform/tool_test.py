"""Unit tests for search_opportunities — no agent, session, or LLM call involved (per SPEC.md's
"must be unit-testable in isolation" requirement). save_user_profile/load_user_profile need an
active Agent Kernel session (they call ToolContext.get()) and are exercised instead by
demo_test.py's live smoke test.
"""

from tool import search_opportunities


def test_returns_top_skill_match_first():
    results = search_opportunities(skills=["coding", "teaching"], causes=[], location=None, remote_ok=True)
    assert results, "Expected at least one match for coding + teaching"
    top = results[0]
    assert "coding" in [s.lower() for s in top["required_skills"]]
    assert "teaching" in [s.lower() for s in top["required_skills"]]


def test_skill_match_outranks_cause_only_match():
    # v018 matches the "coding" skill directly; v005 only matches the "youth development" cause.
    results = search_opportunities(skills=["coding"], causes=["youth development"], location=None, remote_ok=True)
    ids = [r["id"] for r in results]
    assert "v018" in ids and "v005" in ids
    assert ids.index("v018") < ids.index("v005")


def test_case_insensitive_matching():
    lower = search_opportunities(skills=["cooking"], causes=[], location=None, remote_ok=False)
    upper = search_opportunities(skills=["COOKING"], causes=[], location=None, remote_ok=False)
    assert [r["id"] for r in lower] == [r["id"] for r in upper]


def test_location_match_without_remote():
    results = search_opportunities(skills=[], causes=[], location="Galle", remote_ok=False)
    assert results, "Expected at least one match for Galle"
    assert all(r["location"] == "Galle" for r in results)


def test_remote_ok_surfaces_remote_opportunities():
    results = search_opportunities(skills=["coding"], causes=[], location=None, remote_ok=True)
    assert any(r["remote"] for r in results)


def test_no_match_returns_empty_list():
    results = search_opportunities(
        skills=["quantum computing"], causes=["space exploration"], location="Antarctica", remote_ok=False
    )
    assert results == []


def test_no_match_with_remote_ok_returns_empty_list():
    # Regression: remote listings used to "match" any profile on remote_ok alone, so a user whose
    # skills/causes overlap nothing still got 5 unrelated remote opportunities.
    results = search_opportunities(
        skills=["quantum computing"], causes=["space exploration"], location="Antarctica", remote_ok=True
    )
    assert results == []


def test_remote_only_overlap_is_not_a_match():
    results = search_opportunities(skills=["coding"], causes=[], location=None, remote_ok=True)
    assert results
    assert all("coding" in [s.lower() for s in r["required_skills"]] for r in results)


def test_results_capped_at_five():
    # "no experience needed" appears on many entries — a broad query should still cap at 5.
    results = search_opportunities(skills=["no experience needed"], causes=[], location=None, remote_ok=True)
    assert len(results) <= 5


def test_every_result_has_a_justification():
    results = search_opportunities(skills=["gardening"], causes=["environment"], location=None, remote_ok=True)
    assert results
    assert all(r["justification"] for r in results)
