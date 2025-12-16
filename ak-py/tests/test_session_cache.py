from agentkernel.core.base import Session
from agentkernel.core.session.base import SessionCache


def test_session_cache_init():
    cache = SessionCache(capacity=3)
    assert cache.capacity() == 3
    assert len(cache._cache) == 0


def test_session_cache_set_get():
    cache = SessionCache(capacity=2)
    session1 = Session("session1")
    session2 = Session("session2")

    cache.set(session1)
    assert cache.size() == 1

    cache.set(session2)
    assert cache.size() == 2

    assert cache.get("session1") == session1
    assert cache.get("session2") == session2
    assert cache.get("nonexistent") is None


def test_session_cache_clear():
    cache = SessionCache(capacity=2)
    session1 = Session("session1")
    session2 = Session("session2")

    cache.set(session1)
    cache.set(session2)

    cache.clear()

    assert cache.get("session1") is None
    assert cache.get("session2") is None
    assert cache.size() == 0


def test_session_cache_lru_on_set():
    cache = SessionCache(capacity=2)
    session1 = Session("session1")
    session2 = Session("session2")
    session3 = Session("session3")

    cache.set(session1)
    cache.set(session2)
    cache.set(session3)  # This should evict session1

    assert cache.get("session1") is None
    assert cache.get("session2") == session2
    assert cache.get("session3") == session3


def test_session_cache_lru_on_get():
    cache = SessionCache(capacity=2)
    session1 = Session("session1")
    session2 = Session("session2")
    session3 = Session("session3")

    cache.set(session1)
    cache.set(session2)

    assert cache.get("session1") == session1  # Access session1 to mark it as recently used
    cache.set(session3)  # This should evict session2

    assert cache.get("session1") == session1
    assert cache.get("session2") is None
    assert cache.get("session3") == session3
