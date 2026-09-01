import asyncio
import logging

from .service import CourseService

logger = logging.getLogger(__name__)


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

    def submit(self, owner, course_id, action, document_id=None):
        course = self.store.get(owner, "course", course_id)
        if len(self.tasks) >= 3:
            raise ValueError("The local model queue is full. Please retry when a job finishes.")
        if any(j["status"] in {"queued", "running"} for j in self.store.list(owner, "job", course_id)):
            raise ValueError("This course already has an active job.")
        if not self.store.allow(f"model:{owner}", 20, 3600):
            raise ValueError("Hourly analysis limit reached. Please try again later.")
        if action == "extract":
            document = self.store.get(owner, "document", document_id)
            if document["course_id"] != course_id or not document.get("approved"):
                raise ValueError("Approve a document in this course first.")
            if document["role"] not in {"paper", "syllabus", "notes"}:
                raise ValueError("Assessment guidance is used directly during comparison, not as syllabus objectives.")
        job = self.store.put(
            owner,
            "job",
            course_id,
            {"action": action, "status": "queued", "revision": course["revision"], "error": None, "acknowledged": False},
        )
        task = asyncio.create_task(self._work(owner, course_id, job, document_id))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return job

    async def _work(self, owner, course_id, job, document_id):
        try:
            async with self.lock:
                job["status"] = "running"
                self.store.put(owner, "job", course_id, job, job["id"])
                course = self.store.get(owner, "course", course_id)
                if course["revision"] != job["revision"]:
                    raise ValueError("Course changed while queued. Please retry against the new version.")
                engine = self.model()
                async with asyncio.timeout(900):
                    if job["action"] == "extract":
                        document = self.store.get(owner, "document", document_id)
                        result = await engine.extract(owner, course_id, document)
                    else:
                        documents, objectives, questions = self.service.materials(owner, course_id)
                        if not objectives or not questions:
                            raise ValueError("Approve at least one objective and one question before comparing.")
                        result = await engine.analyze(owner, course, documents, objectives, questions)
                current = self.store.get(owner, "course", course_id)
                if current["revision"] != job["revision"]:
                    raise ValueError("Course changed during analysis. Results were discarded; retry the current version.")
                if job["action"] == "extract":
                    for kind, items in (("objective", result.objectives), ("question", result.questions)):
                        existing = self.store.list(owner, kind, course_id)
                        limit = 30 if kind == "objective" else 50
                        new = [i for i in items if not any(r["evidence"] == i.evidence.model_dump() for r in existing)]
                        if len(existing) + len(new) > limit:
                            raise ValueError("Course item limit reached. Use a smaller topic.")
                        for item in new:
                            self.store.put(owner, kind, course_id, {**item.model_dump(), "approved": False})
                    self.store.update_course(owner, course_id)
                else:
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
