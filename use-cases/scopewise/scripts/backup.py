"""Create a consistent SQLite backup while the app is running."""

import argparse
import sqlite3
from pathlib import Path

from scopewise.app import Settings


def backup(source: Path, destination: Path):
    if not source.is_file():
        raise ValueError("Source database does not exist.")
    if destination.exists():
        raise ValueError("Backup destination already exists; choose a new filename.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Create with restrictive permissions before copying any private data.
    destination.touch(mode=0o600, exist_ok=False)
    try:
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src, sqlite3.connect(destination) as dst:
            src.backup(dst)
            if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Backup integrity check failed.")
    except Exception:
        destination.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    backup(Settings.from_env().data_dir / "scopewise.sqlite3", args.destination)
    print("Consistent backup created. Store it privately; it contains uploaded material and account data.")
