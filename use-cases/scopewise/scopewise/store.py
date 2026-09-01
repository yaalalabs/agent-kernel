import json
import sqlite3
import struct
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS resources (
                  id TEXT PRIMARY KEY, owner TEXT NOT NULL, kind TEXT NOT NULL,
                  course_id TEXT REFERENCES resources(id) ON DELETE CASCADE,
                  payload TEXT NOT NULL, created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS resource_owner ON resources(owner, kind, course_id);
                CREATE TABLE IF NOT EXISTS users (
                  id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                  token TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
                  csrf TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS telegram_links (
                  chat_id TEXT PRIMARY KEY, owner TEXT NOT NULL UNIQUE);
                CREATE TABLE IF NOT EXISTS link_codes (
                  code TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS telegram_updates (
                  update_id INTEGER PRIMARY KEY, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS rate_limits (
                  key TEXT PRIMARY KEY, count INTEGER NOT NULL, resets REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS document_chunks (
                  id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                  course_id TEXT NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
                  document_id TEXT NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
                  page INTEGER NOT NULL, ordinal INTEGER NOT NULL, text TEXT NOT NULL,
                  embedding BLOB, embed_model TEXT);
                CREATE INDEX IF NOT EXISTS chunk_course ON document_chunks(owner, course_id, document_id);
            """)
        path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _read(db, owner, kind, item_id):
        row = db.execute("SELECT payload FROM resources WHERE id=? AND owner=? AND kind=?", (item_id, owner, kind)).fetchone()
        if row is None:
            raise KeyError("Resource not found")
        return json.loads(row["payload"])

    def get(self, owner, kind, item_id):
        with self.connect() as db:
            return self._read(db, owner, kind, item_id)

    def list(self, owner, kind, course_id=None):
        with self.connect() as db:
            if course_id:
                self._read(db, owner, "course", course_id)
                rows = db.execute("SELECT payload FROM resources WHERE owner=? AND kind=? AND course_id=? ORDER BY created", (owner, kind, course_id))
            else:
                rows = db.execute("SELECT payload FROM resources WHERE owner=? AND kind=? ORDER BY created", (owner, kind))
            return [json.loads(row["payload"]) for row in rows]

    def put(self, owner, kind, course_id, payload, item_id=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if course_id:
                self._read(db, owner, "course", course_id)
            if item_id:
                self._read(db, owner, kind, item_id)
            item_id = item_id or uuid.uuid4().hex
            payload = {**payload, "id": item_id, "course_id": course_id}
            db.execute(
                "INSERT INTO resources VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                (item_id, owner, kind, course_id, json.dumps(payload), time.time()),
            )
            return payload

    def create_course(self, owner, title, lecturer=""):
        if len(self.list(owner, "course")) >= 10:
            raise ValueError("Course limit reached. Delete a course before adding another.")
        return self.put(owner, "course", None, {"title": title, "lecturer": lecturer, "revision": 1, "scope_version": 1, "assessment_version": 1})

    def update_course(self, owner, course_id, *, lecturer=None, title=None, scope=False, assessment=False):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            course = self._read(db, owner, "course", course_id)
            if lecturer is not None and lecturer != course["lecturer"]:
                course["lecturer"] = lecturer
                assessment = True
                # A new lecturer does not prove a new exam style. Existing guidance
                # must be explicitly reconfirmed for this teaching context.
                rows = db.execute("SELECT id,payload FROM resources WHERE owner=? AND kind='document' AND course_id=?", (owner, course_id)).fetchall()
                for row in rows:
                    document = json.loads(row["payload"])
                    if document.get("role") == "guidance":
                        document["approved"] = False
                        db.execute("UPDATE resources SET payload=? WHERE id=?", (json.dumps(document), row["id"]))
            if title is not None:
                course["title"] = title
            course["revision"] += 1
            course["scope_version"] += int(scope)
            course["assessment_version"] += int(assessment)
            db.execute("UPDATE resources SET payload=? WHERE id=? AND owner=?", (json.dumps(course), course_id, owner))
            return course

    def delete_course(self, owner, course_id):
        with self.connect() as db:
            self._read(db, owner, "course", course_id)
            db.execute("DELETE FROM resources WHERE id=? AND owner=?", (course_id, owner))

    def replace_chunks(self, owner, course_id, document_id, chunks):
        with self.connect() as db:
            self._read(db, owner, "course", course_id)
            document = self._read(db, owner, "document", document_id)
            if document["course_id"] != course_id:
                raise KeyError("Resource not found")
            db.execute("DELETE FROM document_chunks WHERE owner=? AND document_id=?", (owner, document_id))
            for chunk in chunks:
                db.execute(
                    "INSERT INTO document_chunks VALUES (?,?,?,?,?,?,?,?,NULL)",
                    (
                        uuid.uuid4().hex,
                        owner,
                        course_id,
                        document_id,
                        chunk["page"],
                        chunk["ordinal"],
                        chunk["text"],
                        None,
                    ),
                )

    def update_chunk_embeddings(self, owner, document_id, vectors, model):
        with self.connect() as db:
            document = self._read(db, owner, "document", document_id)
            rows = db.execute(
                "SELECT id FROM document_chunks WHERE owner=? AND document_id=? ORDER BY page, ordinal", (owner, document_id)
            ).fetchall()
            if len(rows) != len(vectors):
                raise ValueError("Document changed while its semantic index was being created.")
            for row, vector in zip(rows, vectors):
                packed = struct.pack(f"<{len(vector)}f", *vector)
                db.execute("UPDATE document_chunks SET embedding=?, embed_model=? WHERE id=?", (packed, model, row["id"]))
            return document

    def list_chunks(self, owner, course_id, document_ids=None):
        with self.connect() as db:
            self._read(db, owner, "course", course_id)
            params = [owner, course_id]
            sql = "SELECT * FROM document_chunks WHERE owner=? AND course_id=?"
            if document_ids is not None:
                ids = list(document_ids)
                if not ids:
                    return []
                sql += " AND document_id IN (" + ",".join("?" for _ in ids) + ")"
                params.extend(ids)
            sql += " ORDER BY document_id, page, ordinal"
            result = []
            for row in db.execute(sql, params):
                item = dict(row)
                blob = item.pop("embedding")
                item["embedding"] = list(struct.unpack(f"<{len(blob) // 4}f", blob)) if blob else None
                result.append(item)
            return result

    def allow(self, key, limit, window=60):
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM rate_limits WHERE resets < ?", (now,))
            row = db.execute("SELECT count FROM rate_limits WHERE key=?", (key,)).fetchone()
            if row and row["count"] >= limit:
                return False
            db.execute("INSERT INTO rate_limits VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1", (key, now + window))
            return True
