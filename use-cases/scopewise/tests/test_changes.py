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
