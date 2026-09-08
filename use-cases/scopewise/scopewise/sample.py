"""Original synthetic material. These reviewed fixtures are not model output."""

from .models import Evidence, Match, Objective, Question


def seed_sample(store, owner):
    course = store.create_course(owner, "Database systems", "Dr. Sen — current teaching profile")
    cid = course["id"]
    syllabus = store.put(
        owner,
        "document",
        cid,
        {
            "name": "Current module outline.txt",
            "role": "syllabus",
            "approved": True,
            "lecturer": "Dr. Sen",
            "year": "2026",
            "pages": [
                (
                    "SYNTHETIC DEMONSTRATION MATERIAL\nLearning objectives:\nExplain primary keys and distinguish "
                    "candidate keys.\nApply third normal form to a small relational schema.\nConstruct SQL joins to "
                    "combine two related tables.\nBCNF proofs are explicitly excluded from this module."
                )
            ],
            "content": "",
            "mime": "text/plain",
        },
    )
    guidance = store.put(
        owner,
        "document",
        cid,
        {
            "name": "Current assessment guidance.txt",
            "role": "guidance",
            "approved": True,
            "lecturer": "Dr. Sen",
            "year": "2026",
            "pages": [
                (
                    "SYNTHETIC DEMONSTRATION MATERIAL\nCurrent assessment guidance: keys are assessed through worked "
                    "schema examples, rather than standalone definitions. Normalisation questions require an "
                    "explanation of the dependencies and the resulting third-normal-form tables. This is practice "
                    "guidance, not a prediction of future questions."
                )
            ],
            "content": "",
            "mime": "text/plain",
        },
    )
    paper = store.put(
        owner,
        "document",
        cid,
        {
            "name": "Earlier lecturer — practice paper.txt",
            "role": "paper",
            "approved": True,
            "lecturer": "Dr. Perera",
            "year": "2023",
            "pages": [
                (
                    "SYNTHETIC DEMONSTRATION MATERIAL\nQ1. Define a primary key and a candidate key.\nQ2. Given "
                    "Enrolment(student_id, student_name, course_id, course_name), with student_id determining "
                    "student_name and course_id determining course_name, decompose into third normal form and "
                    "explain each dependency.\nQ3. Define a primary key and a candidate key.\nQ4. Prove that every "
                    "BCNF relation is in third normal form.\nQ5. Explain why indexing can improve query performance."
                )
            ],
            "content": "",
            "mime": "text/plain",
        },
    )
    objectives = []
    for text, kind in [
        ("Explain primary keys and distinguish candidate keys.", "required"),
        ("Apply third normal form to a small relational schema.", "required"),
        ("Construct SQL joins to combine two related tables.", "required"),
        ("BCNF proofs are explicitly excluded from this module.", "excluded"),
    ]:
        obj = Objective(text=text, kind=kind, approved=True, evidence=Evidence(document_id=syllabus["id"], page=1, quote=text))
        objectives.append(store.put(owner, "objective", cid, obj.model_dump()))
    texts = [
        "Define a primary key and a candidate key.",
        (
            "Given Enrolment(student_id, student_name, course_id, course_name), with student_id determining "
            "student_name and course_id determining course_name, decompose into third normal form and "
            "explain each dependency."
        ),
        "Define a primary key and a candidate key.",
        "Prove that every BCNF relation is in third normal form.",
        "Explain why indexing can improve query performance.",
    ]
    questions = []
    for index, text in enumerate(texts, 1):
        q = Question(text=text, label=f"Q{index}", approved=True, evidence=Evidence(document_id=paper["id"], page=1, quote=text))
        questions.append(store.put(owner, "question", cid, q.model_dump()))
    matches = []
    for index, question in enumerate(questions):
        objective_index = {0: 0, 1: 1, 2: 0, 3: 3}.get(index)
        match = Match(
            question_id=question["id"],
            reviewed=True,
            objective_ids=[objectives[objective_index]["id"]] if objective_index is not None else [],
            scope_status="beyond_scope" if index == 3 else "uncertain" if index == 4 else "aligned",
            reason=[
                "The key definitions match the objective, but the expected assessment format differs.",
                "This is a worked 3NF decomposition with dependencies, matching the objective and current guidance.",
                "Exact repeat of Q1; keep one copy in the pack.",
                "The current module explicitly excludes BCNF proofs.",
                "Indexing is not established by the supplied outline. Absence is not proof of exclusion.",
            ][index],
            evidence=[Evidence.model_validate(objectives[objective_index]["evidence"])] if objective_index is not None else [],
        )
        if index in {0, 1, 2}:
            match.assessment_status = "matches_guidance" if index == 1 else "different_format"
            match.assessment_reason = (
                "Current guidance expects a worked example with dependencies."
                if index == 1
                else (
                    "Current guidance expects worked schema examples rather than standalone definitions. This old "
                    "question remains useful basic practice."
                )
            )
            match.assessment_evidence = [
                Evidence(
                    document_id=guidance["id"],
                    page=1,
                    quote="Normalisation questions require an explanation of the dependencies and the resulting third-normal-form tables."
                    if index == 1
                    else "keys are assessed through worked schema examples, rather than standalone definitions.",
                )
            ]
        matches.append(match.model_dump())
    store.put(
        owner,
        "analysis",
        cid,
        {
            "matches": matches,
            "revision": course["revision"],
            "scope_version": 1,
            "assessment_version": 1,
            "origin": "human-reviewed synthetic demonstration; not model output",
        },
    )
    return course
