import asyncio

from scopewise.jobs import Jobs
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
    from scopewise.models import Analysis

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
