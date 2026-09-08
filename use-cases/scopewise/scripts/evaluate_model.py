"""Small synthetic development regression, NOT a real-course accuracy benchmark."""

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path

from scopewise.agents import KernelEngine
from scopewise.candidates import select_candidates
from scopewise.models import Question
from scopewise.sample import seed_sample
from scopewise.service import CourseService
from scopewise.store import Store

ADVERSARIAL = [
    ("Explain why indexing improves query performance.", "uncertain"),
    ("Prove that every BCNF relation is in third normal form.", "beyond_scope"),
    ("Distinguish a primary key from a candidate key.", "aligned"),
    ("Explain B+ tree leaf-node splitting.", "uncertain"),
    ("Decompose the supplied relation into third normal form.", "aligned"),
    ("State the definition of third normal form.", "partial"),
    ("Write a join combining customer and order tables.", "aligned"),
    ("Use relational division to find students taking every course.", "uncertain"),
]


async def main():
    with tempfile.TemporaryDirectory() as directory:
        store = Store(Path(directory) / "evaluation.db")
        course = seed_sample(store, "evaluation")
        service = CourseService(store)
        documents, objectives, sample_questions = service.materials("evaluation", course["id"])
        source_evidence = sample_questions[0].evidence
        engine = KernelEngine(store, service.prepare_pack)
        rows = []
        try:
            for index, (text, expected_status) in enumerate(ADVERSARIAL, 1):
                question = Question(id=f"adversarial-{index}", text=text, label=f"A{index}", evidence=source_evidence, approved=True)
                semantic_scores = await engine._semantic_scores(text, objectives)
                selection = select_candidates(text, objectives, semantic_scores)
                started = time.monotonic()
                row = {
                    "question": text,
                    "expected_scope": expected_status,
                    "candidate_mode": selection.mode,
                    "selected_objectives": [
                        {"id": objective.id, "kind": objective.kind, "text": objective.text} for objective in selection.objectives
                    ],
                }
                try:
                    result = await engine.analyze("evaluation", course, documents, objectives, [question])
                    match = result.matches[0]
                    trace = engine.run_trace[0] if engine.run_trace else {}
                    row.update(
                        actual_scope=match.scope_status,
                        scope_correct=match.scope_status == expected_status,
                        discarded_references=trace.get("discarded_references", 0),
                        result=match.model_dump(),
                    )
                except Exception as exc:
                    row.update(
                        actual_scope="error",
                        scope_correct=False,
                        discarded_references=sum(event.get("discarded_references", 0) for event in engine.run_trace),
                        error=type(exc).__name__,
                    )
                row["seconds"] = round(time.monotonic() - started, 1)
                rows.append(row)
                print(json.dumps(row), flush=True)
        finally:
            await engine.close()
        Path("output").mkdir(exist_ok=True)
        report = {
            "model": os.getenv("SCOPEWISE_MODEL", "llama3.1:latest"),
            "notice": "Eight synthetic adversarial questions used during development; not independent or representative accuracy evidence.",
            "rows": rows,
        }
        Path("output/local-evaluation.json").write_text(json.dumps(report, indent=2))
        print("Scope correct:", sum(row["scope_correct"] for row in rows), f"/ {len(rows)}")


if __name__ == "__main__":
    asyncio.run(main())
