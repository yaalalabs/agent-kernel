from .matching import build_pack, validate_evidence, validate_match
from .models import Match, Objective, Question


def typed(cls, record):
    return cls.model_validate({k: v for k, v in record.items() if k in cls.model_fields})


class CourseService:
    def __init__(self, store):
        self.store = store

    def bundle(self, owner, course_id):
        course = self.store.get(owner, "course", course_id)
        result = {"course": course}
        for kind in ("document", "objective", "question", "analysis", "pack", "job"):
            records = self.store.list(owner, kind, course_id)
            if kind == "document":
                records = [{k: v for k, v in d.items() if k != "content"} for d in records]
            if kind in {"analysis", "pack"}:
                records = [{**r, "stale": r["revision"] != course["revision"]} for r in records]
            if kind == "pack":
                records = [{**r, "stale": self.pack_stale(owner, r)} for r in records]
            result["analyses" if kind == "analysis" else kind + "s"] = records
        return result

    def pack_stale(self, owner, pack):
        course = self.store.get(owner, "course", pack["course_id"])
        analysis = self.store.get(owner, "analysis", pack["analysis_id"])
        return pack["revision"] != course["revision"] or pack.get("review_version", 0) != analysis.get("review_version", 0)

    def manual_review(self, owner, course_id):
        course = self.store.get(owner, "course", course_id)
        _, objectives, questions = self.materials(owner, course_id)
        if not objectives or not questions:
            raise ValueError("Approve at least one objective and question first.")
        return self.store.put(
            owner,
            "analysis",
            course_id,
            {
                "revision": course["revision"],
                "scope_version": course["scope_version"],
                "assessment_version": course["assessment_version"],
                "review_version": 0,
                "origin": "manual evidence review; no model output",
                "matches": [Match(question_id=q.id, reason="Awaiting your evidence review.").model_dump() for q in questions],
            },
        )

    def materials(self, owner, course_id):
        documents = self.store.list(owner, "document", course_id)
        objectives = [typed(Objective, o) for o in self.store.list(owner, "objective", course_id) if o.get("approved")]
        questions = [typed(Question, q) for q in self.store.list(owner, "question", course_id) if q.get("approved")]
        return documents, objectives, questions

    def save_item(self, owner, course_id, kind, payload, item_id=None):
        cls = {"objective": Objective, "question": Question}.get(kind)
        if cls is None:
            raise ValueError("Unsupported item type.")
        documents = self.store.list(owner, "document", course_id)
        item = cls.model_validate(payload)
        document = validate_evidence(item.evidence, documents)
        if not document.get("approved"):
            raise ValueError("Review and approve the source document first.")
        if kind == "objective" and document["role"] not in {"syllabus", "notes"}:
            raise ValueError("Current objectives must cite a syllabus or current notes.")
        if kind == "question" and document["role"] != "paper":
            raise ValueError("Practice questions must cite a past paper.")
        if item_id and self.store.get(owner, kind, item_id)["course_id"] != course_id:
            raise KeyError("Resource not found")
        if not item_id and len(self.store.list(owner, kind, course_id)) >= (30 if kind == "objective" else 50):
            raise ValueError("This pilot supports 30 objectives and 50 questions per course.")
        saved = self.store.put(owner, kind, course_id, item.model_dump(), item_id)
        self.store.update_course(owner, course_id, scope=kind == "objective")
        return saved

    def approve_document(self, owner, document_id, approved):
        document = self.store.get(owner, "document", document_id)
        if approved and document["role"] == "syllabus":
            for old in self.store.list(owner, "document", document["course_id"]):
                if old["id"] != document_id and old["role"] == "syllabus" and old.get("approved"):
                    self.approve_document(owner, old["id"], False)
        document["approved"] = approved
        result = self.store.put(owner, "document", document["course_id"], document, document_id)
        if not approved:
            for kind in ("objective", "question"):
                for item in self.store.list(owner, kind, document["course_id"]):
                    if item["evidence"]["document_id"] == document_id:
                        self.store.put(owner, kind, document["course_id"], {**item, "approved": False}, item["id"])
        self.store.update_course(owner, document["course_id"], assessment=document["role"] == "guidance", scope=document["role"] == "syllabus")
        return {k: v for k, v in result.items() if k != "content"}

    def review_match(self, owner, analysis_id, match):
        analysis = self.store.get(owner, "analysis", analysis_id)
        course = self.store.get(owner, "course", analysis["course_id"])
        if analysis["revision"] != course["revision"]:
            raise ValueError("This analysis is stale. Re-analyze the current course before reviewing it.")
        documents, objectives, questions = self.materials(owner, course["id"])
        checked = validate_match(Match.model_validate(match), documents, objectives, questions)
        if checked.question_id not in {m["question_id"] for m in analysis["matches"]}:
            raise ValueError("Question is not in this analysis.")
        analysis["matches"] = [checked.model_dump() if m["question_id"] == checked.question_id else m for m in analysis["matches"]]
        analysis["review_version"] = analysis.get("review_version", 0) + 1
        return self.store.put(owner, "analysis", course["id"], analysis, analysis_id)

    def prepare_pack(self, owner, course_id, limit=8):
        course = self.store.get(owner, "course", course_id)
        analyses = self.store.list(owner, "analysis", course_id)
        if not analyses or analyses[-1]["revision"] != course["revision"]:
            raise ValueError("Run a current analysis and review its matches before making a pack.")
        analysis = analyses[-1]
        _, objectives, questions = self.materials(owner, course_id)
        pack = build_pack(objectives, questions, [Match.model_validate(m) for m in analysis["matches"]], limit)
        if not pack["questions"]:
            raise ValueError("Review at least one suitable match before making a pack.")
        pack.update(
            {
                "revision": course["revision"],
                "scope_version": course["scope_version"],
                "assessment_version": course["assessment_version"],
                "analysis_id": analysis["id"],
                "review_version": analysis.get("review_version", 0),
                "title": course["title"],
                "origin": analysis.get("origin", "model suggestions reviewed by user"),
                "objectives": [o.model_dump() for o in objectives],
            }
        )
        return self.store.put(owner, "pack", course_id, pack)
