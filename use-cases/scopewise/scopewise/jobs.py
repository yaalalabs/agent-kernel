import asyncio
import logging

from .matching import build_pack
from .models import Match
from .service import CourseService

logger = logging.getLogger(__name__)

TRACE_FIELDS = {
    "question_id",
    "agent",
    "retrieval_mode",
    "candidate_objective_count",
    "exclusions_checked",
    "guidance_chunks",
    "discarded_references",
    "exclusion_enforced",
    "human_review_required",
}


def safe_trace(engine):
    events = []
    for raw in list(getattr(engine, "run_trace", []))[:50]:
        if not isinstance(raw, dict):
            continue
        event = {key: value for key, value in raw.items() if key in TRACE_FIELDS and isinstance(value, (str, int, bool))}
        if event:
            events.append(event)
    return events


class Jobs:
    def __init__(self, store, engine_factory):
        self.store = store
        self.service = CourseService(store)
        self.engine_factory = engine_factory
        self.engine = None
        self.lock = asyncio.Lock()
        self.tasks = set()
        with store.connect() as db:
            # A single process owns jobs. Interrupted jobs remain inspectable after restart.
            import json

            for row in db.execute("SELECT id,payload FROM resources WHERE kind='job'").fetchall():
                data = json.loads(row["payload"])
                if data.get("status") in {"queued", "running"}:
                    data.update(status="failed", error="Server restarted before this job finished. Retry it.")
                    db.execute("UPDATE resources SET payload=? WHERE id=?", (json.dumps(data), row["id"]))

    def model(self):
        if self.engine is None:
            self.engine = self.engine_factory(self.store, self.service.prepare_pack)
        return self.engine

    def submit(self, owner, course_id, action, document_id=None, document_ids=None, limit=None, difficulty="medium"):
        course = self.store.get(owner, "course", course_id)
        if action not in {"extract", "analyze", "prepare", "generate_pack"}:
            raise ValueError("Unsupported model job.")
        if len(self.tasks) >= 3:
            raise ValueError("The local model queue is full. Please retry when a job finishes.")
        if any(j["status"] in {"queued", "running"} for j in self.store.list(owner, "job", course_id)):
            raise ValueError("This course already has an active job.")
        if not self.store.allow(f"model:{owner}", 20, 3600):
            raise ValueError("Hourly analysis limit reached. Please try again later.")
        if action == "analyze":
            _, objectives, questions = self.service.materials(owner, course_id)
            if not objectives or not questions:
                documents = list(reversed(self.store.list(owner, "document", course_id)))
                scope = next((item for item in documents if item["role"] in {"syllabus", "notes"}), None)
                paper = next((item for item in documents if item["role"] == "paper"), None)
                guidance = next((item for item in documents if item["role"] == "guidance"), None)
                if not scope or not paper:
                    raise ValueError("Upload current module material and a past paper before preparing the comparison.")
                action = "prepare"
                document_ids = [scope["id"], paper["id"], *([guidance["id"]] if guidance else [])]
        if action == "extract":
            document = self.store.get(owner, "document", document_id)
            if document["course_id"] != course_id or not document.get("approved"):
                raise ValueError("Approve a document in this course first.")
            if document["role"] not in {"paper", "syllabus", "notes"}:
                raise ValueError("Assessment guidance is used directly during comparison, not as syllabus objectives.")
        if action == "prepare":
            if not isinstance(document_ids, list) or not 2 <= len(document_ids) <= 3:
                raise ValueError("Choose one current-scope file and one past paper. Current assessment guidance is optional.")
            documents = [self.store.get(owner, "document", item_id) for item_id in document_ids]
            if any(document["course_id"] != course_id for document in documents):
                raise ValueError("All setup files must belong to this module.")
            roles = [document["role"] for document in documents]
            scope_count = sum(role in {"syllabus", "notes"} for role in roles)
            if (
                len(set(roles)) != len(roles)
                or scope_count != 1
                or roles.count("paper") != 1
                or roles.count("guidance") > 1
                or not set(roles) <= {"syllabus", "notes", "guidance", "paper"}
            ):
                raise ValueError("Choose one current-scope file and one past paper. Current assessment guidance is optional.")
            for document in documents:
                self.service.approve_document(owner, document["id"], True)
            course = self.store.get(owner, "course", course_id)
        for old_job in self.store.list(owner, "job", course_id):
            if old_job.get("status") == "failed" and not old_job.get("acknowledged"):
                old_job["acknowledged"] = True
                self.store.put(owner, "job", course_id, old_job, old_job["id"])
        if action == "generate_pack" and (not isinstance(limit, int) or not 1 <= limit <= 30):
            raise ValueError("Choose between 1 and 30 questions.")
        if action == "generate_pack" and difficulty not in {"easy", "medium", "difficult"}:
            raise ValueError("Choose easy, medium or difficult generated questions.")
        job = self.store.put(
            owner,
            "job",
            course_id,
            {
                "action": action,
                "status": "queued",
                "revision": course["revision"],
                "error": None,
                "acknowledged": False,
                **({"document_ids": document_ids} if action == "prepare" else {}),
                **({"limit": limit} if action == "generate_pack" else {}),
                **({"difficulty": difficulty} if action == "generate_pack" else {}),
            },
        )
        task = asyncio.create_task(self._work(owner, course_id, job, document_id, document_ids, limit, difficulty))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return job

    async def _prepare(self, owner, course_id, job, document_ids, engine):
        documents = [self.store.get(owner, "document", item_id) for item_id in document_ids]
        prepared_ids = []
        current = self.store.get(owner, "course", course_id)
        for document in documents:
            if document["role"] not in {"syllabus", "notes", "paper"}:
                continue
            expected_kind = "question" if document["role"] == "paper" else "objective"
            existing_for_document = [
                item for item in self.store.list(owner, expected_kind, course_id) if item.get("evidence", {}).get("document_id") == document["id"]
            ]
            changed = False
            if existing_for_document:
                for item in existing_for_document:
                    if not item.get("approved"):
                        item["approved"] = True
                        self.store.put(owner, expected_kind, course_id, item, item["id"])
                        changed = True
                    prepared_ids.append(item["id"])
            else:
                result = await engine.extract(owner, course_id, document)
                if self.store.get(owner, "course", course_id)["revision"] != job["revision"]:
                    raise ValueError("Course changed during preparation. Retry the current version.")
                for kind, items in (("objective", result.objectives), ("question", result.questions)):
                    for item in items:
                        existing = self.store.list(owner, kind, course_id)
                        match = next((saved for saved in existing if saved["evidence"] == item.evidence.model_dump()), None)
                        if match:
                            if not match.get("approved"):
                                match["approved"] = True
                                self.store.put(owner, kind, course_id, match, match["id"])
                                changed = True
                            prepared_ids.append(match["id"])
                            continue
                        limit = 30 if kind == "objective" else 50
                        if len(existing) >= limit:
                            raise ValueError("Course item limit reached. Use a smaller topic.")
                        saved = self.store.put(owner, kind, course_id, {**item.model_dump(), "approved": True})
                        prepared_ids.append(saved["id"])
                        changed = True
            if changed:
                current = self.store.update_course(owner, course_id, scope=expected_kind == "objective")
                job["revision"] = current["revision"]
                job["prepared_item_ids"] = prepared_ids
                self.store.put(owner, "job", course_id, job, job["id"])

        current = self.store.get(owner, "course", course_id)
        job["revision"] = current["revision"]
        job["prepared_item_ids"] = prepared_ids

        material_documents, objectives, questions = self.service.materials(owner, course_id)
        if not objectives:
            raise ValueError("No usable learning objectives were found in the current-material file. Try a module outline or learning-outcomes file.")
        if not questions:
            raise ValueError("No usable questions were found in the past-paper file. Scanned PDFs need selectable text or OCR.")
        result = await engine.analyze(owner, current, material_documents, objectives, questions)
        if self.store.get(owner, "course", course_id)["revision"] != current["revision"]:
            raise ValueError("Course changed during comparison. Results were discarded; retry the current version.")
        job["trace"] = safe_trace(engine)
        record = self.store.put(
            owner,
            "analysis",
            course_id,
            {
                **result.model_dump(),
                "revision": current["revision"],
                "scope_version": current["scope_version"],
                "assessment_version": current["assessment_version"],
                "origin": "local model; human review required",
                "provenance": {event["question_id"]: event for event in job["trace"] if event.get("question_id")},
            },
        )
        job["result_id"] = record["id"]

    async def _generate_pack(self, owner, course_id, course, job, limit, difficulty, engine):
        analyses = self.store.list(owner, "analysis", course_id)
        if not analyses or analyses[-1]["revision"] != course["revision"]:
            raise ValueError("Prepare a current question review before generating a pack.")
        analysis = analyses[-1]
        documents, objectives, questions = self.service.materials(owner, course_id)
        pack = build_pack(objectives, questions, [Match.model_validate(match) for match in analysis["matches"]], limit)
        generated = []
        missing = limit - len(pack["questions"])
        if missing:
            generated = await engine.generate_questions(owner, course, documents, objectives, questions, missing, difficulty)
            pack["questions"].extend(generated[:missing])
            required_ids = {objective.id for objective in objectives if objective.kind == "required"}
            generated_coverage = {objective_id for question in generated[:missing] for objective_id in question["match"].get("objective_ids", [])}
            covered = set(pack["covered_objective_ids"]) | (generated_coverage & required_ids)
            pack["covered_objective_ids"] = sorted(covered)
            pack["uncovered_objective_ids"] = sorted(required_ids - covered)
        if self.store.get(owner, "course", course_id)["revision"] != course["revision"]:
            raise ValueError("Course changed during question generation. Results were discarded; retry the current version.")
        if not pack["questions"]:
            raise ValueError("No suitable or generated questions were available for this pack.")
        pack.update(
            {
                "revision": course["revision"],
                "scope_version": course["scope_version"],
                "assessment_version": course["assessment_version"],
                "analysis_id": analysis["id"],
                "review_version": analysis.get("review_version", 0),
                "title": course["title"],
                "origin": "local model; reviewed source questions plus labeled AI-generated practice",
                "objectives": [objective.model_dump() for objective in objectives],
                "source_question_count": len(pack["questions"]) - len(generated[:missing]),
                "generated_count": len(generated[:missing]),
                "generation_difficulty": difficulty,
                "available_unique_questions": len(pack["questions"]),
                "notice": (
                    "AI-generated questions are grounded in confirmed objectives and current guidance when available. "
                    "They are practice suggestions, require inspection, and are not exam predictions."
                ),
            }
        )
        record = self.store.put(owner, "pack", course_id, pack)
        job["result_id"] = record["id"]

    async def _work(self, owner, course_id, job, document_id, document_ids=None, limit=None, difficulty="medium"):
        try:
            async with self.lock:
                job["status"] = "running"
                self.store.put(owner, "job", course_id, job, job["id"])
                course = self.store.get(owner, "course", course_id)
                if course["revision"] != job["revision"]:
                    raise ValueError("Course changed while queued. Please retry against the new version.")
                engine = self.model()
                try:
                    async with asyncio.timeout(900):
                        if job["action"] == "extract":
                            document = self.store.get(owner, "document", document_id)
                            result = await engine.extract(owner, course_id, document)
                        elif job["action"] == "prepare":
                            await self._prepare(owner, course_id, job, document_ids, engine)
                            result = None
                        elif job["action"] == "generate_pack":
                            await self._generate_pack(owner, course_id, course, job, limit, difficulty, engine)
                            result = None
                        else:
                            documents, objectives, questions = self.service.materials(owner, course_id)
                            if not objectives or not questions:
                                raise ValueError("Approve at least one objective and one question before comparing.")
                            result = await engine.analyze(owner, course, documents, objectives, questions)
                finally:
                    job["trace"] = safe_trace(engine)
                current = self.store.get(owner, "course", course_id)
                if current["revision"] != job["revision"]:
                    raise ValueError("Course changed during analysis. Results were discarded; retry the current version.")
                if job["action"] == "extract":
                    pending = []
                    for kind, items in (("objective", result.objectives), ("question", result.questions)):
                        existing = self.store.list(owner, kind, course_id)
                        limit = 30 if kind == "objective" else 50
                        new = [i for i in items if not any(r["evidence"] == i.evidence.model_dump() for r in existing)]
                        if len(existing) + len(new) > limit:
                            raise ValueError("Course item limit reached. Use a smaller topic.")
                        pending.extend((kind, item) for item in new)
                    for kind, item in pending:
                        self.store.put(owner, kind, course_id, {**item.model_dump(), "approved": False})
                    if pending:
                        self.store.update_course(owner, course_id)
                elif job["action"] == "analyze":
                    record = self.store.put(
                        owner,
                        "analysis",
                        course_id,
                        {
                            **result.model_dump(),
                            "revision": course["revision"],
                            "scope_version": course["scope_version"],
                            "assessment_version": course["assessment_version"],
                            "origin": "local model; human review required",
                            "provenance": {event["question_id"]: event for event in job["trace"] if event.get("question_id")},
                        },
                    )
                    job["result_id"] = record["id"]
                job["status"] = "completed"
        except asyncio.CancelledError:
            job.update(status="failed", error="Job interrupted by server shutdown. Retry it.")
        except ValueError as exc:
            job.update(status="failed", error=str(exc)[:400])
        except Exception as exc:
            logger.warning("Model job failed: %s", type(exc).__name__)
            job.update(
                status="failed",
                error=(
                    "The local model did not return a usable result. Check Ollama, retry a smaller input, or use "
                    "manual evidence review. No result was accepted."
                ),
            )
        finally:
            try:
                self.store.put(owner, "job", course_id, job, job["id"])
            except KeyError:
                pass  # Course was deleted while a job was in flight.

    async def close(self):
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)
        if self.engine:
            await self.engine.close()
