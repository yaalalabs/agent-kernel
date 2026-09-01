from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scopewise.app import Settings, create_app


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(data_dir=tmp_path, invitation="test-classroom-invitation", semantic_index=False))


def account(client, username="alice"):
    assert (
        client.post(
            "/api/auth/register", json={"username": username, "password": "correct-horse-battery", "invitation": "test-classroom-invitation"}
        ).status_code
        == 200
    )
    result = client.post("/api/auth/login", json={"username": username, "password": "correct-horse-battery"})
    assert result.status_code == 200
    client.headers["X-CSRF-Token"] = result.json()["csrf"]


def test_course_isolation_and_csrf(app):
    with TestClient(app) as alice, TestClient(app) as bob:
        account(alice)
        course = alice.post("/api/courses", json={"title": "Databases", "lecturer": "Lecturer A"}).json()
        account(bob, "bob")
        assert bob.get(f"/api/courses/{course['id']}").status_code == 404
        assert bob.delete(f"/api/courses/{course['id']}").status_code == 404
        del alice.headers["X-CSRF-Token"]
        assert alice.delete(f"/api/courses/{course['id']}").status_code == 403


def test_sample_pack_becomes_stale_after_lecturer_change(app):
    with TestClient(app) as client:
        account(client)
        course = client.post("/api/sample").json()
        pack = client.post(f"/api/courses/{course['id']}/packs", json={"limit": 5}).json()
        assert len(pack["questions"]) >= 2
        assert "synthetic" in pack["origin"]
        updated = client.patch(f"/api/courses/{course['id']}", json={"lecturer": "New lecturer"})
        assert updated.json()["assessment_version"] == 2
        assert client.post(f"/api/courses/{course['id']}/packs", json={"limit": 5}).status_code == 400
        assert client.get(f"/api/packs/{pack['id']}/export").status_code == 409
        bundle = client.get(f"/api/courses/{course['id']}").json()
        assert bundle["packs"][0]["stale"]
        assert all(not d["approved"] for d in bundle["documents"] if d["role"] == "guidance")


def test_upload_requires_review_and_download_is_private(app):
    with TestClient(app) as client:
        account(client)
        course = client.post("/api/courses", json={"title": "Databases"}).json()
        result = client.post(
            f"/api/courses/{course['id']}/documents",
            data={"role": "syllabus"},
            files={"file": ("syllabus.txt", b"Explain primary keys and relational models.", "text/plain")},
        )
        assert result.status_code == 200
        doc = result.json()
        assert not doc["approved"]
        assert "content" not in doc
        assert client.get(f"/api/documents/{doc['id']}/download").status_code == 200
        client.post("/api/auth/logout")
        assert client.get(f"/api/documents/{doc['id']}/download").status_code == 401


def test_uploaded_text_is_chunked_and_searchable_with_exact_source_location(app):
    with TestClient(app) as client:
        account(client)
        course = client.post("/api/courses", json={"title": "Algorithms"}).json()
        uploaded = client.post(
            f"/api/courses/{course['id']}/documents",
            data={"role": "notes"},
            files={"file": ("trees.md", b"AVL rotations preserve balance after insertion and deletion.", "text/markdown")},
        ).json()
        assert uploaded["index_status"] == "lexical"
        assert uploaded["chunk_count"] == 1
        results = client.get(f"/api/courses/{course['id']}/source-search", params={"q": "balance deletion"})
        assert results.status_code == 200
        assert results.json()["mode"] == "lexical"
        assert results.json()["results"][0]["document_id"] == uploaded["id"]
        assert results.json()["results"][0]["page"] == 1


def test_failed_job_can_be_dismissed(app):
    with TestClient(app) as client:
        account(client)
        identity = client.get("/api/me").json()
        course = client.post("/api/courses", json={"title": "Databases"}).json()
        job = app.state.store.put(
            identity["id"],
            "job",
            course["id"],
            {"action": "analyze", "status": "failed", "revision": 1, "error": "bad alias", "acknowledged": False},
        )
        response = client.patch(f"/api/jobs/{job['id']}", json={"acknowledged": True})
        assert response.status_code == 200
        assert response.json()["acknowledged"] is True


def test_production_requires_secure_configuration():
    with pytest.raises(ValueError):
        Settings(data_dir=Path("unused"), production=True, invitation="weak")


def test_actual_body_size_is_bounded_even_with_false_length(app):
    with TestClient(app) as client:
        response = client.post("/api/auth/register", content=b"x" * 129000, headers={"Content-Type": "application/json", "Content-Length": "10"})
        assert response.status_code == 413


def test_changing_a_review_invalidates_packs_built_from_it(app):
    with TestClient(app) as client:
        account(client)
        course = client.post("/api/sample").json()
        bundle = client.get(f"/api/courses/{course['id']}").json()
        pack = client.post(f"/api/courses/{course['id']}/packs", json={"limit": 5}).json()
        analysis = bundle["analyses"][-1]
        match = {**analysis["matches"][0], "reviewed": False}
        assert client.patch(f"/api/analyses/{analysis['id']}/matches", json=match).status_code == 200
        assert client.get(f"/api/packs/{pack['id']}/export").status_code == 409


def test_manual_review_is_explicitly_labeled_and_works_without_model(app):
    with TestClient(app) as client:
        account(client)
        course = client.post("/api/sample").json()
        response = client.post(f"/api/courses/{course['id']}/manual-review")
        assert response.status_code == 200
        assert response.json()["origin"] == "manual evidence review; no model output"
        assert all(not m["reviewed"] and m["scope_status"] == "uncertain" for m in response.json()["matches"])


def test_client_cannot_mutate_server_authored_analysis_provenance(app):
    with TestClient(app) as client:
        account(client)
        owner = client.get("/api/me").json()["id"]
        course = client.post("/api/sample").json()
        analysis = client.get(f"/api/courses/{course['id']}").json()["analyses"][-1]
        question_id = analysis["matches"][0]["question_id"]
        analysis["provenance"] = {question_id: {"agent": "scopewise_align"}}
        app.state.store.put(owner, "analysis", course["id"], analysis, analysis["id"])
        attempted_match = {**analysis["matches"][0], "provenance": {"agent": "client-forged"}}

        response = client.patch(f"/api/analyses/{analysis['id']}/matches", json=attempted_match)

        assert response.status_code == 422
        stored = app.state.store.get(owner, "analysis", analysis["id"])
        assert stored["provenance"][question_id]["agent"] == "scopewise_align"


def test_bundle_keeps_earlier_analysis_without_provenance(app):
    with TestClient(app) as client:
        account(client)
        course = client.post("/api/sample").json()

        analysis = client.get(f"/api/courses/{course['id']}").json()["analyses"][-1]

        assert "provenance" not in analysis
