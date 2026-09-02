import time

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
        result["change_impact"] = self.change_impact(owner, course_id)
        return result

    def record_change(self, owner, course_id, event_type, summary, affected=None, document_ids=None):
        course = self.store.get(owner, "course", course_id)
        checked_document_ids = []
        for document_id in document_ids or []:
            document = self.store.get(owner, "document", document_id)
            if document["course_id"] != course_id:
                raise KeyError("Resource not found")
            checked_document_ids.append(document_id)
        counts = {
            str(key)[:50]: max(0, int(value))
            for key, value in list((affected or {}).items())[:10]
            if isinstance(value, int) and not isinstance(value, bool)
        }
        return self.store.put(
            owner,
            "change_event",
            course_id,
            {
                "type": str(event_type)[:60],
                "revision": course["revision"],
                "created": time.time(),
                "summary": str(summary)[:300],
                "affected": counts,
                "document_ids": checked_document_ids[:12],
            },
        )

    def edit_course(self, owner, course_id, *, lecturer=None, title=None):
        old = self.store.get(owner, "course", course_id)
        lecturer_changed = lecturer is not None and lecturer != old["lecturer"]
        title_changed = title is not None and title != old["title"]
        if not lecturer_changed and not title_changed:
            return old
        approved_guidance = [
            document for document in self.store.list(owner, "document", course_id) if document.get("role") == "guidance" and document.get("approved")
        ]
        course = self.store.update_course(owner, course_id, lecturer=lecturer, title=title)
        if lecturer_changed:
            self.record_change(
                owner,
                course_id,
                "lecturer_changed",
                "Lecturer changed. This does not prove the assessment format changed; current guidance must be reconfirmed.",
                affected={"guidance_reconfirmation": len(approved_guidance)},
                document_ids=[document["id"] for document in approved_guidance],
            )
        return course

    def change_impact(self, owner, course_id):
        course = self.store.get(owner, "course", course_id)
        documents = self.store.list(owner, "document", course_id)
        document_by_id = {document["id"]: document for document in documents}
        objectives = self.store.list(owner, "objective", course_id)
        analyses = self.store.list(owner, "analysis", course_id)
        packs = self.store.list(owner, "pack", course_id)
        events = list(reversed(self.store.list(owner, "change_event", course_id)))[:10]
        stale_analysis_count = sum(analysis["revision"] != course["revision"] for analysis in analyses)
        stale_pack_count = sum(self.pack_stale(owner, pack) for pack in packs)
        retired_objective_count = sum(
            document_by_id.get(objective.get("evidence", {}).get("document_id"), {}).get("role") == "syllabus"
            and not document_by_id.get(objective.get("evidence", {}).get("document_id"), {}).get("approved")
            for objective in objectives
        )
        has_current_guidance = any(document.get("role") == "guidance" and document.get("approved") for document in documents)
        has_required_scope = any(objective.get("kind") == "required" and objective.get("approved") for objective in objectives)
        guidance_requires_review = any(event["type"] in {"lecturer_changed", "guidance_changed"} for event in events)
        lecturer_changed = any(event["type"] == "lecturer_changed" for event in events)
        if not has_current_guidance and guidance_requires_review:
            next_action = "sources"
        elif not has_required_scope:
            next_action = "scope"
        elif not analyses or stale_analysis_count:
            next_action = "review"
        else:
            next_action = "packs"
        statement = (
            "A lecturer change does not prove that the assessment format changed. Reconfirm current guidance before comparing assessment fit."
            if lecturer_changed and not has_current_guidance
            else "ScopeWise tracks accepted course changes and marks dependent analysis or practice packs for review."
        )
        return {
            "latest_event": events[0] if events else None,
            "scope_version": course["scope_version"],
            "assessment_version": course["assessment_version"],
            "stale_analysis_count": stale_analysis_count,
            "stale_pack_count": stale_pack_count,
            "retired_objective_count": retired_objective_count,
            "has_current_guidance": has_current_guidance,
            "next_action": next_action,
            "statement": statement,
            "events": events,
        }

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
        current = self.store.get(owner, kind, item_id) if item_id else None
        if current and current["course_id"] != course_id:
            raise KeyError("Resource not found")
        if not item_id and len(self.store.list(owner, kind, course_id)) >= (30 if kind == "objective" else 50):
            raise ValueError("This pilot supports 30 objectives and 50 questions per course.")
        if current and typed(cls, current).model_dump() == item.model_dump():
            return current
        saved = self.store.put(owner, kind, course_id, item.model_dump(), item_id)
        self.store.update_course(owner, course_id, scope=kind == "objective")
        if kind == "objective":
            self.record_change(
                owner,
                course_id,
                "scope_changed",
                "An approved scope item changed. Existing comparisons must be reviewed against the current scope.",
                affected={"objectives": 1},
                document_ids=[item.evidence.document_id],
            )
        return saved

    def approve_document(self, owner, document_id, approved):
        document = self.store.get(owner, "document", document_id)
        if document.get("approved") is approved:
            return {k: v for k, v in document.items() if k != "content"}
        retired_objectives = 0
        replaced_syllabi = []
        if approved and document["role"] == "syllabus":
            replaced_syllabi = [
                old
                for old in self.store.list(owner, "document", document["course_id"])
                if old["id"] != document_id and old["role"] == "syllabus" and old.get("approved")
            ]
            for old in replaced_syllabi:
                self.store.put(owner, "document", document["course_id"], {**old, "approved": False}, old["id"])
                for objective in self.store.list(owner, "objective", document["course_id"]):
                    if objective["evidence"]["document_id"] == old["id"] and objective.get("approved"):
                        retired_objectives += 1
                        self.store.put(owner, "objective", document["course_id"], {**objective, "approved": False}, objective["id"])
        document["approved"] = approved
        result = self.store.put(owner, "document", document["course_id"], document, document_id)
        if not approved:
            for kind in ("objective", "question"):
                for item in self.store.list(owner, kind, document["course_id"]):
                    if item["evidence"]["document_id"] == document_id:
                        self.store.put(owner, kind, document["course_id"], {**item, "approved": False}, item["id"])
        self.store.update_course(owner, document["course_id"], assessment=document["role"] == "guidance", scope=document["role"] == "syllabus")
        if replaced_syllabi:
            self.record_change(
                owner,
                document["course_id"],
                "syllabus_replaced",
                "The approved syllabus changed. Objectives tied to the earlier syllabus were retired pending review.",
                affected={"retired_objectives": retired_objectives},
                document_ids=[document_id, *(old["id"] for old in replaced_syllabi)],
            )
        elif document["role"] == "guidance":
            self.record_change(
                owner,
                document["course_id"],
                "guidance_changed",
                "Current assessment guidance approval changed. Assessment-fit judgments require review.",
                affected={"guidance_documents": 1},
                document_ids=[document_id],
            )
        else:
            self.record_change(
                owner,
                document["course_id"],
                "source_approval_changed",
                "A source approval changed. Dependent objectives, questions, and comparisons require review.",
                affected={"documents": 1},
                document_ids=[document_id],
            )
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
        current_match = next(item for item in analysis["matches"] if item["question_id"] == checked.question_id)
        if Match.model_validate(current_match).model_dump() == checked.model_dump():
            return analysis
        analysis["matches"] = [checked.model_dump() if m["question_id"] == checked.question_id else m for m in analysis["matches"]]
        analysis["review_version"] = analysis.get("review_version", 0) + 1
        result = self.store.put(owner, "analysis", course["id"], analysis, analysis_id)
        affected_packs = sum(pack.get("analysis_id") == analysis_id for pack in self.store.list(owner, "pack", course["id"]))
        self.record_change(
            owner,
            course["id"],
            "judgment_changed",
            "A human-reviewed judgment changed. Practice packs built from this review may be stale.",
            affected={"packs": affected_packs},
        )
        return result

    def review_suitable_matches(self, owner, analysis_id):
        analysis = self.store.get(owner, "analysis", analysis_id)
        course = self.store.get(owner, "course", analysis["course_id"])
        if analysis["revision"] != course["revision"]:
            raise ValueError("This analysis is stale. Re-analyze the current course before reviewing it.")
        documents, objectives, questions = self.materials(owner, course["id"])
        updated, changed = [], 0
        for raw in analysis["matches"]:
            match = validate_match(Match.model_validate(raw), documents, objectives, questions)
            if match.scope_status in {"aligned", "partial"} and not match.reviewed:
                match.reviewed = True
                changed += 1
            updated.append(match.model_dump())
        if not changed:
            return analysis
        analysis["matches"] = updated
        analysis["review_version"] = analysis.get("review_version", 0) + 1
        result = self.store.put(owner, "analysis", course["id"], analysis, analysis_id)
        affected_packs = sum(pack.get("analysis_id") == analysis_id for pack in self.store.list(owner, "pack", course["id"]))
        self.record_change(
            owner,
            course["id"],
            "judgments_batch_confirmed",
            f"{changed} suitable recommendations were confirmed together by the user.",
            affected={"matches": changed, "packs": affected_packs},
        )
        return result

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
