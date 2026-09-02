"""Runs synthetic material through the real local model and Agent Kernel."""

import asyncio
import json
import tempfile
from pathlib import Path

from scopewise.agents import KernelEngine
from scopewise.sample import seed_sample
from scopewise.service import CourseService
from scopewise.store import Store


async def main():
    with tempfile.TemporaryDirectory() as directory:
        store = Store(Path(directory) / "smoke.db")
        course = store.create_course("smoke-user", "Synthetic databases", "Demo lecturer")
        document = store.put(
            "smoke-user",
            "document",
            course["id"],
            {
                "name": "Synthetic syllabus",
                "role": "syllabus",
                "approved": True,
                "pages": [
                    (
                        "Learning objectives:\nExplain primary keys and distinguish candidate keys.\nApply third normal "
                        "form to a small relational schema.\nBCNF proofs are excluded from this module."
                    )
                ],
            },
        )
        engine = KernelEngine(store, lambda *args: {"notice": "No reviewed practice questions in this smoke test."})
        try:
            result = await engine.extract("smoke-user", course["id"], document)
            print(json.dumps({"extracted_count": len(result.objectives), "objectives": [o.model_dump() for o in result.objectives]}, indent=2))
            for objective in result.objectives:
                store.put("smoke-user", "objective", course["id"], objective.model_dump())
            response = await engine.chat(
                "smoke-user", course["id"], "Read my course overview using your tool and tell me the course title and scope version."
            )
            assert "get_course_overview" in engine.tool_events, "Assistant must actually execute the course tool"
            print("ASSISTANT:", response)
            print("VERIFIED TOOL CALLS:", engine.tool_events)
            sample = seed_sample(store, "smoke-user")
            service = CourseService(store)
            sample = service.edit_course("smoke-user", sample["id"], lecturer="Changed synthetic lecturer")
            change_response = await engine.chat("smoke-user", sample["id"], "What changed? Use the course change-impact tool before answering.")
            assert "get_change_impact" in engine.tool_events, "Assistant must execute the change-impact tool"
            print("CHANGE IMPACT:", change_response)
            print("VERIFIED CHANGE TOOL CALLS:", engine.tool_events)
            documents, objectives, questions = service.materials("smoke-user", sample["id"])
            comparison = await engine.analyze("smoke-user", sample, documents, objectives, questions)
            print("LIVE COMPARISON (unreviewed):", comparison.model_dump_json(indent=2))
            generated = await engine.generate_questions("smoke-user", sample, documents, objectives, questions, 2, "medium")
            assert generated and all(question["generated"] for question in generated)
            print(
                "LIVE GENERATED PRACTICE:",
                json.dumps(
                    [
                        {"text": question["text"], "difficulty": question["difficulty"], "objective_ids": question["match"]["objective_ids"]}
                        for question in generated
                    ],
                    indent=2,
                ),
            )
        finally:
            await engine.close()


if __name__ == "__main__":
    asyncio.run(main())
