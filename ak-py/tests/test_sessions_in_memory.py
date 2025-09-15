import pytest

from ak.core.sessions.in_memory import InMemorySessionStore


def test_in_memory_session_store_new_and_load():
    store = InMemorySessionStore()
    s1 = store.new("abc")
    assert s1.id == "abc"
    s1.set("k", 1)
    store.store(s1)

    loaded = store.load("abc", strict=True)
    assert loaded.get("k") == 1


def test_in_memory_session_store_load_missing_strict():
    store = InMemorySessionStore()
    with pytest.raises(KeyError):
        store.load("missing", strict=True)


def test_in_memory_session_store_load_missing_creates_when_not_strict():
    store = InMemorySessionStore()
    s = store.load("x", strict=False)
    assert s.id == "x"


def test_in_memory_session_clear():
    store = InMemorySessionStore()
    store.new("one")
    store.new("two")
    assert len(list(store._sessions.keys())) == 2
    store.clear()
    assert list(store._sessions.keys()) == []
