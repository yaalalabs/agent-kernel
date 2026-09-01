import asyncio
import json

from scopewise.jobs import Jobs
from scopewise.models import Analysis, Match
from scopewise.sample import seed_sample
from scopewise.store import Store


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
