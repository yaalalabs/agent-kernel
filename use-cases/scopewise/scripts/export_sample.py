"""Write the original demonstration source files for a fresh-upload demo."""

import tempfile
from pathlib import Path

from scopewise.sample import seed_sample
from scopewise.store import Store


def main():
    output = Path("sample_data")
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        store = Store(Path(directory) / "sample.db")
        course = seed_sample(store, "sample-export")
        for doc in store.list("sample-export", "document", course["id"]):
            (output / doc["name"]).write_text("\f".join(doc["pages"]), encoding="utf-8")
    print("Original synthetic sample source files written to sample_data/.")


if __name__ == "__main__":
    main()
