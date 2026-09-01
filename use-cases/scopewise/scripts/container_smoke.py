"""Exercise an isolated local container with disposable synthetic data."""

import argparse
import secrets

import httpx


def main(base):
    if base not in {"http://127.0.0.1:8081", "http://localhost:8081"}:
        raise SystemExit("This disposable smoke test is restricted to localhost:8081.")
    with httpx.Client(base_url=base, timeout=35, trust_env=False) as client:
        assert client.get("/health").json()["status"] == "ok"
        credentials = {"username": "smoke_" + secrets.token_hex(4), "password": secrets.token_urlsafe(24), "invitation": "scopewise-local"}
        assert client.post("/api/auth/register", json=credentials).status_code == 200
        login = client.post("/api/auth/login", json=credentials)
        assert login.status_code == 200
        client.headers["X-CSRF-Token"] = login.json()["csrf"]
        course = client.post("/api/sample").json()
        result = client.post(f"/api/courses/{course['id']}/packs", json={"limit": 5})
        assert result.status_code == 200
        pack = result.json()
        assert len(pack["questions"]) == 2 and pack["duplicates_omitted"] == 1
        assert client.get(f"/api/packs/{pack['id']}/export").status_code == 200
        upload = client.post(
            f"/api/courses/{course['id']}/documents",
            data={"role": "notes"},
            files={"file": ("smoke.txt", b"Explain SQL joins using two related tables.", "text/plain")},
        )
        assert upload.status_code == 200, upload.text
        assert not upload.json()["approved"]
        assert client.get(f"/api/packs/{pack['id']}/export").status_code == 409
        assert client.delete(f"/api/courses/{course['id']}").status_code == 200
        assert client.get(f"/api/documents/{upload.json()['id']}/download").status_code == 404
        print("PASS: container health, auth, CSRF, sample pack, export, Linux parser subprocess, stale-pack rejection and deletion cascade.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?", default="http://127.0.0.1:8081")
    main(parser.parse_args().url)
