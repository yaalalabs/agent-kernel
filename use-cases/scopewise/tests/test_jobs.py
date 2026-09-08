import asyncio
import json

from scopewise.jobs import Jobs
from scopewise.models import Analysis, Evidence, Extraction, Match, Objective, Question
from scopewise.sample import seed_sample
from scopewise.store import Store


async def test_duplicate_only_extraction_does_not_stale_the_course(tmp_path):
    store = Store(tmp_path / "jobs.db")
    course = store.create_course("alice", "Databases")
    document = store.put(
        "alice",
        "document",
        course["id"],
        {"name": "scope.txt", "role": "syllabus", "approved": True, "pages": ["Explain primary keys."]},
    )
    evidence = Evidence(document_id=document["id"], page=1, quote="Explain primary keys.")
    store.put(
        "alice",
        "objective",
        course["id"],
        Objective(text="Explain primary keys", evidence=evidence, approved=False).model_dump(),
    )

    class DuplicateEngine:
        def __init__(self, *args):
            self.run_trace = []

        async def extract(self, *args):
            return Extraction(objectives=[Objective(text="Explain primary keys", evidence=evidence)])

        async def close(self):
            pass

    jobs = Jobs(store, DuplicateEngine)
    job = jobs.submit("alice", course["id"], "extract", document["id"])
    await asyncio.gather(*list(jobs.tasks))

    assert store.get("alice", "job", job["id"])["status"] == "completed"
    assert store.get("alice", "course", course["id"])["revision"] == course["revision"]
    assert len(store.list("alice", "objective", course["id"])) == 1
    await jobs.close()


async def test_provider_failure_is_a_failed_job_not_a_fake_analysis(tmp_path):
    store = Store(tmp_path / "jobs.db")
    course = seed_sample(store, "alice")

    class OfflineEngine:
        def __init__(self, *args):
            pass

        async def analyze(self, *args):
            raise ConnectionError("private-provider-details")

        async def close(self):
            pass

    jobs = Jobs(store, OfflineEngine)
    job = jobs.submit("alice", course["id"], "analyze")
    await asyncio.gather(*list(jobs.tasks))
    saved = store.get("alice", "job", job["id"])
    assert saved["status"] == "failed"
    assert "private-provider-details" not in saved["error"]
    assert len(store.list("alice", "analysis", course["id"])) == 1  # only the labeled sample
    await jobs.close()


async def test_course_change_during_inference_discards_result(tmp_path):
    store = Store(tmp_path / "jobs.db")
    course = seed_sample(store, "alice")
    entered, finish = asyncio.Event(), asyncio.Event()

    class DelayedEngine:
        def __init__(self, *args):
            pass

        async def analyze(self, *args):
            entered.set()
            await finish.wait()
            return Analysis(matches=[])

        async def close(self):
            pass

    jobs = Jobs(store, DelayedEngine)
    job = jobs.submit("alice", course["id"], "analyze")
    await entered.wait()
    store.update_course("alice", course["id"], lecturer="Another lecturer")
    finish.set()
    await asyncio.gather(*list(jobs.tasks))
    assert store.get("alice", "job", job["id"])["status"] == "failed"
    assert len(store.list("alice", "analysis", course["id"])) == 1
    await jobs.close()


async def test_completed_analysis_job_persists_bounded_safe_provenance(tmp_path):
    store = Store(tmp_path / "jobs.db")
    course = seed_sample(store, "alice")

    class TracedEngine:
        def __init__(self, *args):
            self.run_trace = []

        async def analyze(self, *args):
            questions = args[-1]
            question_id = questions[0].id
            self.run_trace = [
                {
                    "question_id": question_id,
                    "agent": "scopewise_align",
                    "retrieval_mode": "lexical",
                    "candidate_objective_count": 1,
                    "exclusions_checked": 1,
                    "guidance_chunks": 0,
                    "discarded_references": 0,
                    "human_review_required": True,
                    "owner": "alice",
                    "prompt": "private model prompt",
                    "vector": [0.1, 0.2],
                    "session_id": "private-session",
                }
            ]
            return Analysis(matches=[Match(question_id=question.id, reason="Manual review required.") for question in questions])

        async def close(self):
            pass

    jobs = Jobs(store, TracedEngine)
    job = jobs.submit("alice", course["id"], "analyze")
    await asyncio.gather(*list(jobs.tasks))

    saved_job = store.get("alice", "job", job["id"])
    saved_analysis = store.list("alice", "analysis", course["id"])[-1]
    question_id = saved_job["trace"][0]["question_id"]
    assert saved_analysis["provenance"][question_id] == saved_job["trace"][0]
    serialized = json.dumps(saved_job["trace"])
    assert all(forbidden not in serialized for forbidden in ("owner", "prompt", "vector", "session_id"))
    await jobs.close()


async def test_prepare_job_turns_three_uploaded_sources_into_an_unreviewed_comparison(tmp_path):
    store = Store(tmp_path / "jobs.db")
    course = store.create_course("alice", "Databases")
    syllabus = store.put(
        "alice",
        "document",
        course["id"],
        {"name": "scope.txt", "role": "syllabus", "approved": False, "pages": ["Explain primary keys."]},
    )
    guidance = store.put(
        "alice",
        "document",
        course["id"],
        {"name": "guidance.txt", "role": "guidance", "approved": False, "pages": ["Use worked examples."]},
    )
    paper = store.put(
        "alice",
        "document",
        course["id"],
        {"name": "paper.txt", "role": "paper", "approved": False, "pages": ["Define a primary key."]},
    )

    class PrepareEngine:
        def __init__(self, *args):
            self.run_trace = []

        async def extract(self, owner, course_id, document):
            if document["role"] == "syllabus":
                evidence = Evidence(document_id=document["id"], page=1, quote="Explain primary keys.")
                return Extraction(objectives=[Objective(text="Explain primary keys", evidence=evidence)])
            evidence = Evidence(document_id=document["id"], page=1, quote="Define a primary key.")
            return Extraction(questions=[Question(text="Define a primary key", label="Q1", evidence=evidence)])

        async def analyze(self, owner, current_course, documents, objectives, questions):
            self.run_trace = [
                {
                    "question_id": questions[0].id,
                    "agent": "scopewise_align",
                    "retrieval_mode": "lexical",
                    "candidate_objective_count": 1,
                    "exclusions_checked": 0,
                    "guidance_chunks": 1,
                    "discarded_references": 0,
                    "human_review_required": True,
                }
            ]
            return Analysis(matches=[Match(question_id=questions[0].id, reason="Human review required.")])

        async def close(self):
            pass

    jobs = Jobs(store, PrepareEngine)
    job = jobs.submit("alice", course["id"], "prepare", document_ids=[syllabus["id"], guidance["id"], paper["id"]])
    await asyncio.gather(*list(jobs.tasks))

    saved_job = store.get("alice", "job", job["id"])
    assert saved_job["status"] == "completed"
    assert all(document["approved"] for document in store.list("alice", "document", course["id"]))
    assert all(item["approved"] for item in store.list("alice", "objective", course["id"]))
    assert all(item["approved"] for item in store.list("alice", "question", course["id"]))
    analysis = store.list("alice", "analysis", course["id"])[-1]
    assert analysis["origin"] == "local model; human review required"
    assert all(not match["reviewed"] for match in analysis["matches"])
    await jobs.close()


async def test_analyze_with_uploaded_files_retries_automatic_preparation_and_clears_old_failures(tmp_path):
    store = Store(tmp_path / "jobs.db")
    course = store.create_course("alice", "Databases")
    syllabus = store.put(
        "alice",
        "document",
        course["id"],
        {"name": "scope.txt", "role": "notes", "approved": True, "pages": ["Explain primary keys."]},
    )
    paper = store.put(
        "alice",
        "document",
        course["id"],
        {"name": "paper.txt", "role": "paper", "approved": True, "pages": ["Define a primary key."]},
    )
    failed = store.put(
        "alice",
        "job",
        course["id"],
        {"action": "prepare", "status": "failed", "revision": course["revision"], "error": "old error", "acknowledged": False},
    )

    class PrepareEngine:
        def __init__(self, *args):
            self.run_trace = []

        async def extract(self, owner, course_id, document):
            evidence = Evidence(document_id=document["id"], page=1, quote=document["pages"][0])
            if document["role"] == "paper":
                return Extraction(questions=[Question(text=document["pages"][0], evidence=evidence)])
            return Extraction(objectives=[Objective(text=document["pages"][0], evidence=evidence)])

        async def analyze(self, owner, current_course, documents, objectives, questions):
            return Analysis(matches=[Match(question_id=questions[0].id, reason="Check this match.")])

        async def close(self):
            pass

    jobs = Jobs(store, PrepareEngine)
    job = jobs.submit("alice", course["id"], "analyze")
    await asyncio.gather(*list(jobs.tasks))

    assert job["action"] == "prepare"
    assert set(job["document_ids"]) == {syllabus["id"], paper["id"]}
    assert store.get("alice", "job", failed["id"])["acknowledged"] is True
    assert store.get("alice", "job", job["id"])["status"] == "completed"
    await jobs.close()


async def test_prepare_retry_resumes_after_a_later_document_times_out(tmp_path):
    store = Store(tmp_path / "jobs.db")
    course = store.create_course("alice", "Databases")
    syllabus = store.put(
        "alice",
        "document",
        course["id"],
        {"name": "scope.txt", "role": "syllabus", "approved": True, "pages": ["Explain primary keys."]},
    )
    paper = store.put(
        "alice",
        "document",
        course["id"],
        {"name": "paper.txt", "role": "paper", "approved": True, "pages": ["Define a primary key."]},
    )

    class ResumeEngine:
        paper_attempts = 0
        scope_attempts = 0

        def __init__(self, *args):
            self.run_trace = []

        async def extract(self, owner, course_id, document):
            evidence = Evidence(document_id=document["id"], page=1, quote=document["pages"][0])
            if document["role"] == "paper":
                type(self).paper_attempts += 1
                if type(self).paper_attempts == 1:
                    raise TimeoutError
                return Extraction(questions=[Question(text=document["pages"][0], evidence=evidence)])
            type(self).scope_attempts += 1
            return Extraction(objectives=[Objective(text=document["pages"][0], evidence=evidence)])

        async def analyze(self, owner, current_course, documents, objectives, questions):
            return Analysis(matches=[Match(question_id=questions[0].id, reason="Check this match.")])

        async def close(self):
            pass

    first_jobs = Jobs(store, ResumeEngine)
    first = first_jobs.submit("alice", course["id"], "prepare", document_ids=[syllabus["id"], paper["id"]])
    await asyncio.gather(*list(first_jobs.tasks))
    assert store.get("alice", "job", first["id"])["status"] == "failed"
    assert len(store.list("alice", "objective", course["id"])) == 1
    assert len(store.list("alice", "question", course["id"])) == 0
    await first_jobs.close()

    retry_jobs = Jobs(store, ResumeEngine)
    retry = retry_jobs.submit("alice", course["id"], "analyze")
    await asyncio.gather(*list(retry_jobs.tasks))

    assert store.get("alice", "job", retry["id"])["status"] == "completed"
    assert ResumeEngine.scope_attempts == 1
    assert ResumeEngine.paper_attempts == 2
    assert len(store.list("alice", "question", course["id"])) == 1
    await retry_jobs.close()


async def test_generated_pack_fills_requested_limit_with_labeled_grounded_questions(tmp_path):
    store = Store(tmp_path / "jobs.db")
    course = seed_sample(store, "alice")

    class GenerationEngine:
        def __init__(self, *args):
            self.run_trace = []

        async def generate_questions(self, owner, current_course, documents, objectives, questions, count, difficulty):
            objective = next(item for item in objectives if item.kind == "required")
            generated = []
            for index in range(count):
                question_id = f"generated-{index}"
                generated.append(
                    {
                        "id": question_id,
                        "text": f"Apply the confirmed concept in a new worked scenario {index + 1}.",
                        "label": "AI-generated practice",
                        "evidence": objective.evidence.model_dump(),
                        "approved": False,
                        "generated": True,
                        "difficulty": difficulty,
                        "generated_basis": [objective.evidence.model_dump()],
                        "match": Match(
                            question_id=question_id,
                            objective_ids=[objective.id],
                            scope_status="aligned",
                            reason="Generated from confirmed scope.",
                            evidence=[objective.evidence],
                            reviewed=False,
                        ).model_dump(),
                    }
                )
            return generated

        async def close(self):
            pass

    jobs = Jobs(store, GenerationEngine)
    job = jobs.submit("alice", course["id"], "generate_pack", limit=5, difficulty="difficult")
    await asyncio.gather(*list(jobs.tasks))

    saved_job = store.get("alice", "job", job["id"])
    pack = store.list("alice", "pack", course["id"])[-1]
    assert saved_job["status"] == "completed"
    assert len(pack["questions"]) == 5
    assert pack["source_question_count"] == 2
    assert pack["generated_count"] == 3
    assert pack["generation_difficulty"] == "difficult"
    assert all(question["difficulty"] == "difficult" for question in pack["questions"][-3:])
    assert all(question["generated"] for question in pack["questions"][-3:])
    assert all(not question["match"]["reviewed"] for question in pack["questions"][-3:])
    await jobs.close()
