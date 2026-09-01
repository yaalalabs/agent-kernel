"""Small synthetic regression check, NOT a real-course accuracy benchmark."""

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path

from scopewise.agents import KernelEngine
from scopewise.sample import seed_sample
from scopewise.service import CourseService
from scopewise.store import Store


async def main():
    with tempfile.TemporaryDirectory() as directory:
        store = Store(Path(directory) / "evaluation.db")
        course = seed_sample(store, "evaluation")
        service = CourseService(store)
        documents, objectives, questions = service.materials("evaluation", course["id"])
        expected = store.list("evaluation", "analysis", course["id"])[0]["matches"]
        engine = KernelEngine(store, service.prepare_pack)
        rows = []
        try:
            for question, gold in zip(questions, expected, strict=True):
                started = time.monotonic()
                result = await engine.analyze("evaluation", course, documents, objectives, [question])
                match = result.matches[0]
                row = {
                    "question": question.text,
                    "expected_scope": gold["scope_status"],
                    "expected_assessment": gold["assessment_status"],
                    "scope_correct": match.scope_status == gold["scope_status"],
                    "assessment_correct": match.assessment_status == gold["assessment_status"],
                    "objectives_correct": set(match.objective_ids) == set(gold["objective_ids"]),
                    "seconds": round(time.monotonic() - started, 1),
                    "result": match.model_dump(),
                }
                rows.append(row)
                print(json.dumps(row), flush=True)
        finally:
            await engine.close()
        Path("output").mkdir(exist_ok=True)
        report = {
            "model": os.getenv("SCOPEWISE_MODEL", "llama3.1:latest"),
            "notice": "Five synthetic questions used during development; not independent or representative accuracy evidence.",
            "rows": rows,
        }
        Path("output/local-evaluation.json").write_text(json.dumps(report, indent=2))
        print(
            "Scope correct:",
            sum(r["scope_correct"] for r in rows),
            "/ 5; assessment correct:",
            sum(r["assessment_correct"] for r in rows),
            "/ 5; objective sets correct:",
            sum(r["objectives_correct"] for r in rows),
            "/ 5",
        )


if __name__ == "__main__":
    asyncio.run(main())
