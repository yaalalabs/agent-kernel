import pytest

from scopewise.documents import extract_pages
from scopewise.matching import build_pack, validate_match
from scopewise.models import Evidence, Match, Objective, Question
from scopewise.retrieval import chunk_pages
from scopewise.store import Store


def fixtures():
    docs = [
        {"id": "syllabus", "role": "syllabus", "approved": True, "pages": ["Explain primary keys. Apply third normal form. BCNF is excluded."]},
        {"id": "paper", "role": "paper", "approved": True, "pages": ["Q1 Explain primary keys. Q2 Apply third normal form."]},
        {"id": "guide", "role": "guidance", "approved": True, "pages": ["Use worked applications rather than definition-only answers."]},
    ]
    objectives = [
        Objective(id="o1", text="Explain primary keys", evidence=Evidence(document_id="syllabus", page=1, quote="Explain primary keys.")),
        Objective(id="o2", text="Apply third normal form", evidence=Evidence(document_id="syllabus", page=1, quote="Apply third normal form.")),
    ]
    questions = [
        Question(id="q1", text="Explain primary keys.", evidence=Evidence(document_id="paper", page=1, quote="Explain primary keys.")),
        Question(id="q2", text="Apply third normal form.", evidence=Evidence(document_id="paper", page=1, quote="Apply third normal form.")),
        Question(id="q3", text="Explain primary keys!", evidence=Evidence(document_id="paper", page=1, quote="Explain primary keys.")),
    ]
    return docs, objectives, questions


def test_fabricated_citation_cannot_become_an_alignment():
    docs, objectives, questions = fixtures()
    match = Match(
        question_id="q1",
        objective_ids=["o1"],
        scope_status="aligned",
        reason="Definitions match",
        evidence=[Evidence(document_id="syllabus", page=1, quote="Invented curriculum statement")],
    )
    with pytest.raises(ValueError, match="quote"):
        validate_match(match, docs, objectives, questions)


def test_beyond_scope_requires_explicit_exclusion_not_silence():
    docs, objectives, questions = fixtures()
    match = Match(question_id="q1", scope_status="beyond_scope", reason="Not covered", evidence=[objectives[0].evidence])
    checked = validate_match(match, docs, objectives, questions)
    assert checked.scope_status == "uncertain"


def test_lecturer_change_without_current_guidance_cannot_infer_style():
    docs, objectives, questions = fixtures()
    match = Match(
        question_id="q1",
        objective_ids=["o1"],
        scope_status="aligned",
        reason="Definitions match",
        evidence=[objectives[0].evidence],
        assessment_status="different_format",
    )
    checked = validate_match(match, docs[:2], objectives, questions)
    assert checked.scope_status == "aligned"
    assert checked.assessment_status == "unknown"


def test_old_paper_evidence_cannot_certify_current_assessment_style():
    docs, objectives, questions = fixtures()
    match = Match(
        question_id="q1",
        objective_ids=["o1"],
        scope_status="aligned",
        reason="Definitions match",
        evidence=[objectives[0].evidence],
        assessment_status="matches_guidance",
        assessment_evidence=[questions[0].evidence],
    )
    assert validate_match(match, docs, objectives, questions).assessment_status == "unknown"


def test_pack_covers_objectives_and_omits_exact_repeats():
    _, objectives, questions = fixtures()
    matches = [
        Match(question_id="q1", objective_ids=["o1"], scope_status="aligned", reason="Reviewed", reviewed=True),
        Match(question_id="q2", objective_ids=["o2"], scope_status="aligned", reason="Reviewed", reviewed=True),
        Match(question_id="q3", objective_ids=["o1"], scope_status="aligned", reason="Reviewed", reviewed=True),
    ]
    pack = build_pack(objectives, questions, matches, 3)
    assert [q["id"] for q in pack["questions"]] == ["q1", "q2"]
    assert pack["uncovered_objective_ids"] == []
    assert pack["duplicates_omitted"] == 1


def test_partial_match_does_not_claim_full_coverage():
    _, objectives, questions = fixtures()
    matches = [Match(question_id="q1", objective_ids=["o1"], scope_status="partial", reason="Only one aspect", reviewed=True)]
    pack = build_pack(objectives, questions, matches, 3)
    assert pack["covered_objective_ids"] == []
    assert pack["uncovered_objective_ids"] == ["o1", "o2"]


def test_cross_owner_access_and_lecturer_revision(tmp_path):
    store = Store(tmp_path / "test.db")
    course = store.create_course("alice", "Databases", "Original lecturer")
    doc = store.put("alice", "document", course["id"], {"pages": ["private"]})
    with pytest.raises(KeyError):
        store.get("bob", "document", doc["id"])
    with pytest.raises(KeyError):
        store.put("bob", "document", course["id"], {"pages": ["attack"]})
    revised = store.update_course("alice", course["id"], lecturer="New lecturer")
    assert revised["assessment_version"] == 2
    assert revised["scope_version"] == 1
    assert revised["revision"] > course["revision"]


def test_unreadable_or_invalid_file_is_rejected():
    with pytest.raises(ValueError):
        extract_pages(b"not a PDF", "paper.pdf")
    with pytest.raises(ValueError, match="empty"):
        extract_pages(b"   ", "notes.txt")
    assert extract_pages(b"Learning objectives\nExplain primary keys.", "notes.txt") == ["Learning objectives\nExplain primary keys."]


def test_pptx_text_is_extracted_one_slide_per_page():
    import io
    import zipfile

    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as deck:
        deck.writestr("[Content_Types].xml", "<Types/>")
        deck.writestr(
            "ppt/slides/slide1.xml",
            '<p:sld xmlns:p="p" xmlns:a="a"><a:t>Binary search trees</a:t><a:t>Explain rotations</a:t></p:sld>',
        )
        deck.writestr("ppt/slides/slide2.xml", '<p:sld xmlns:p="p" xmlns:a="a"><a:t>AVL deletion</a:t></p:sld>')
    assert extract_pages(data.getvalue(), "week-4.pptx") == ["Binary search trees\nExplain rotations", "AVL deletion"]


def test_page_chunks_keep_exact_text_and_page_numbers():
    source = "A" * 900 + " primary keys " + "B" * 900
    chunks = chunk_pages([source], target=1000, overlap=160)
    assert len(chunks) >= 2
    assert all(chunk["page"] == 1 and chunk["text"] in source for chunk in chunks)
    assert any("primary keys" in chunk["text"] for chunk in chunks)


@pytest.mark.asyncio
async def test_semantic_search_uses_local_vectors_and_preserves_citations(tmp_path, monkeypatch):
    from scopewise import retrieval

    store = Store(tmp_path / "vectors.db")
    course = store.create_course("alice", "Algorithms")
    document = store.put("alice", "document", course["id"], {"name": "notes.txt", "pages": ["trees", "graphs"]})
    store.replace_chunks(
        "alice",
        course["id"],
        document["id"],
        [{"page": 1, "ordinal": 0, "text": "balanced tree rotations"}, {"page": 2, "ordinal": 0, "text": "shortest graph paths"}],
    )
    store.update_chunk_embeddings("alice", document["id"], [[1.0, 0.0], [0.0, 1.0]], "test-embed")

    async def fake_embed(_texts):
        return "test-embed", [[1.0, 0.0]]

    monkeypatch.setattr(retrieval, "embed_texts", fake_embed)
    result = await retrieval.search_chunks(store, "alice", course["id"], "rebalance", semantic=True)
    assert result["mode"] == "semantic"
    assert result["results"][0]["page"] == 1
    assert result["results"][0]["text"] == "balanced tree rotations"


@pytest.mark.asyncio
async def test_document_index_falls_back_without_blocking_upload(tmp_path, monkeypatch):
    from scopewise import retrieval

    store = Store(tmp_path / "fallback.db")
    course = store.create_course("alice", "Algorithms")
    document = store.put("alice", "document", course["id"], {"name": "notes.txt", "pages": ["balanced binary search trees"]})

    async def unavailable(_texts):
        raise OSError("local model offline")

    monkeypatch.setattr(retrieval, "embed_texts", unavailable)
    indexed = await retrieval.index_document(store, "alice", course["id"], document, semantic=True)
    assert indexed["index_status"] == "lexical"
    assert indexed["chunk_count"] == 1
    assert store.list_chunks("alice", course["id"])[0]["text"] == "balanced binary search trees"


def test_quote_for_one_objective_cannot_cover_another_on_same_page():
    docs, objectives, questions = fixtures()
    match = Match(question_id="q1", objective_ids=["o1", "o2"], scope_status="aligned", reason="Both linked", evidence=[objectives[0].evidence])
    assert validate_match(match, docs, objectives, questions).scope_status == "uncertain"
