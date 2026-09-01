import re

from .models import Evidence, Match, Objective, Question


def normalized(text):
    return " ".join(text.split()).casefold()


def validate_evidence(evidence: Evidence, documents: list[dict]):
    document = next((d for d in documents if d["id"] == evidence.document_id), None)
    if document is None or not 1 <= evidence.page <= len(document["pages"]):
        raise ValueError("Evidence refers to an unavailable document or page.")
    if normalized(evidence.quote) not in normalized(document["pages"][evidence.page - 1]):
        raise ValueError("Evidence quote does not occur on the cited source page.")
    return document


def validate_match(match: Match, documents: list[dict], objectives: list[Objective], questions: list[Question]):
    match = match.model_copy(deep=True)
    if match.question_id not in {q.id for q in questions}:
        raise ValueError("Unknown question in model response.")
    lookup = {o.id: o for o in objectives}
    if any(o not in lookup for o in match.objective_ids):
        raise ValueError("Unknown objective in model response.")
    for evidence in match.evidence + match.assessment_evidence:
        validate_evidence(evidence, documents)
    linked = [lookup[o] for o in match.objective_ids]
    has_scope_evidence = bool(linked) and all(
        any(
            e.document_id == o.evidence.document_id and e.page == o.evidence.page and normalized(o.evidence.quote) in normalized(e.quote)
            for e in match.evidence
        )
        for o in linked
    )
    if match.scope_status in {"aligned", "partial"} and (not linked or not has_scope_evidence or any(o.kind == "excluded" for o in linked)):
        match.scope_status = "uncertain"
        match.reason += " Required-objective evidence could not be established."
    if match.scope_status == "beyond_scope" and (not any(o.kind == "excluded" for o in linked) or not has_scope_evidence):
        match.scope_status = "uncertain"
        match.reason += " Absence from supplied notes is not proof of exclusion."
    guidance_ids = {d["id"] for d in documents if d["role"] == "guidance" and d.get("approved")}
    if not match.assessment_evidence or any(e.document_id not in guidance_ids for e in match.assessment_evidence):
        match.assessment_status = "unknown"
        match.assessment_evidence = []
        match.assessment_reason = "No verified current assessment guidance supports a style judgment. Lecturer identity does not predict exam style."
    return match


def build_pack(objectives: list[Objective], questions: list[Question], matches: list[Match], limit: int):
    if not 1 <= limit <= 30:
        raise ValueError("Choose between 1 and 30 questions.")
    required = {o.id for o in objectives if o.kind == "required"}
    by_id = {q.id: q for q in questions}
    eligible, seen, duplicates = [], set(), 0
    for match in matches:
        if not match.reviewed or match.scope_status not in {"aligned", "partial"} or match.question_id not in by_id:
            continue
        question = by_id[match.question_id]
        fingerprint = " ".join(re.findall(r"\w+", question.text.casefold()))
        if fingerprint in seen:
            duplicates += 1
            continue
        seen.add(fingerprint)
        eligible.append((question, match))
    chosen, covered = [], set()
    while eligible and len(chosen) < limit:
        eligible.sort(
            key=lambda pair: (
                len((set(pair[1].objective_ids) & required) - covered) if pair[1].scope_status == "aligned" else 0,
                pair[1].assessment_status == "matches_guidance",
                pair[1].scope_status == "aligned",
            ),
            reverse=True,
        )
        question, match = eligible.pop(0)
        chosen.append({**question.model_dump(), "match": match.model_dump()})
        if match.scope_status == "aligned":
            covered.update(set(match.objective_ids) & required)
    return {
        "questions": chosen,
        "covered_objective_ids": sorted(covered),
        "uncovered_objective_ids": sorted(required - covered),
        "duplicates_omitted": duplicates,
        "notice": (
            "Coverage describes reviewed links to supplied objectives, not exam readiness or predicted questions. Assessment fit may remain unknown."
        ),
    }
