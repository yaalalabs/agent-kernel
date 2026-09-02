import pytest

from scopewise.sample import seed_sample
from scopewise.service import CourseService
from scopewise.store import Store


def test_new_syllabus_retires_old_syllabus_objectives(tmp_path):
    store = Store(tmp_path / "test.db")
    course = seed_sample(store, "alice")
    service = CourseService(store)
    old = next(d for d in store.list("alice", "document", course["id"]) if d["role"] == "syllabus")
    new = store.put(
        "alice",
        "document",
        course["id"],
        {"name": "new.txt", "role": "syllabus", "approved": False, "pages": ["Explain SQL joins in relational databases."]},
    )
    service.approve_document("alice", new["id"], True)
    assert not store.get("alice", "document", old["id"])["approved"]
    assert all(not o["approved"] for o in store.list("alice", "objective", course["id"]) if o["evidence"]["document_id"] == old["id"])
    assert service.bundle("alice", course["id"])["analyses"][-1]["stale"]
    event = store.list("alice", "change_event", course["id"])[-1]
    assert event["type"] == "syllabus_replaced"
    assert event["affected"]["retired_objectives"] == 4


def test_lecturer_change_reports_evidence_safe_impact(tmp_path):
    store = Store(tmp_path / "impact.db")
    course = seed_sample(store, "alice")
    service = CourseService(store)
    service.prepare_pack("alice", course["id"], 5)

    service.edit_course("alice", course["id"], lecturer="New lecturer")
    impact = service.change_impact("alice", course["id"])

    assert impact["stale_analysis_count"] == 1
    assert impact["stale_pack_count"] == 1
    assert impact["has_current_guidance"] is False
    assert impact["next_action"] == "sources"
    assert "does not prove" in impact["statement"]


def test_missing_guidance_stays_the_first_action_after_later_scope_edits(tmp_path):
    store = Store(tmp_path / "impact.db")
    course = seed_sample(store, "alice")
    service = CourseService(store)
    service.edit_course("alice", course["id"], lecturer="New lecturer")
    objective = store.list("alice", "objective", course["id"])[0]
    payload = {key: objective[key] for key in ("text", "kind", "evidence", "approved")}
    payload["text"] = "Explain keys with a relational schema example."

    service.save_item("alice", course["id"], "objective", payload, objective["id"])

    assert service.change_impact("alice", course["id"])["next_action"] == "sources"


def test_change_impact_is_owner_scoped(tmp_path):
    store = Store(tmp_path / "impact.db")
    course = seed_sample(store, "alice")

    with pytest.raises(KeyError):
        CourseService(store).change_impact("bob", course["id"])


def test_document_approval_records_only_real_guidance_changes(tmp_path):
    store = Store(tmp_path / "impact.db")
    course = seed_sample(store, "alice")
    service = CourseService(store)
    guidance = next(document for document in store.list("alice", "document", course["id"]) if document["role"] == "guidance")

    service.approve_document("alice", guidance["id"], False)
    revision = store.get("alice", "course", course["id"])["revision"]
    service.approve_document("alice", guidance["id"], False)
    events = store.list("alice", "change_event", course["id"])

    assert [event["type"] for event in events] == ["guidance_changed"]
    assert store.get("alice", "course", course["id"])["revision"] == revision


def test_scope_and_judgment_edits_are_visible_in_change_history(tmp_path):
    store = Store(tmp_path / "impact.db")
    course = seed_sample(store, "alice")
    service = CourseService(store)
    objective = store.list("alice", "objective", course["id"])[0]
    objective_payload = {key: objective[key] for key in ("text", "kind", "evidence", "approved")}
    objective_payload["text"] = "Explain primary and candidate keys using a relational schema."

    service.save_item("alice", course["id"], "objective", objective_payload, objective["id"])
    analysis = service.manual_review("alice", course["id"])
    reviewed = {**analysis["matches"][0], "reviewed": True}
    service.review_match("alice", analysis["id"], reviewed)
    events = store.list("alice", "change_event", course["id"])

    assert [event["type"] for event in events[-2:]] == ["scope_changed", "judgment_changed"]
