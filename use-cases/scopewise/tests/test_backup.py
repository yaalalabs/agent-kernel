import sqlite3

from scopewise.store import Store
from scripts.backup import backup


def test_backup_restores_private_course_and_passes_integrity(tmp_path):
    source = Store(tmp_path / "source.db")
    course = source.create_course("alice", "Original course")
    backup(source.path, tmp_path / "restored.db")
    restored = Store(tmp_path / "restored.db")
    assert restored.get("alice", "course", course["id"])["title"] == "Original course"
    with sqlite3.connect(restored.path) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
