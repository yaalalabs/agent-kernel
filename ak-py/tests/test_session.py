import pytest

from agentkernel.core.base import Session


def test_session_init():
    session = Session("test-session")
    assert session.id == "test-session"
    assert len(session.get_all_keys()) == 2
    assert session.get_volatile_cache() is not None
    assert len(session.get_volatile_cache().keys()) == 0
    assert session.get_non_volatile_cache() is not None
    assert len(session.get_non_volatile_cache().keys()) == 0


def test_session_set_get():
    session = Session("test-session")
    session.set("key1", "value1")
    assert session.get("key1") == "value1"
    assert "key1" in session.get_all_keys()
    assert session.get("nonexistent") is None


def test_session_delete():
    session = Session("test-session")
    session.set("key1", "value1")
    session.set("key2", "value2")
    session.delete("key1")
    assert session.get("key1") is None
    assert "key1" not in session.get_all_keys()
    assert session.get("key2") == "value2"
    assert "key2" in session.get_all_keys()


def test_session_volatile_cache():
    session = Session("test-session")
    cache = session.get_volatile_cache()
    cache.set("vkey1", "vvalue1")
    assert cache.get("vkey1") == "vvalue1"
    assert "vkey1" in cache.keys()


def test_session_non_volatile_cache():
    session = Session("test-session")
    cache = session.get_non_volatile_cache()
    cache.set("nvkey1", "nvvalue1")
    assert "nvkey1" in cache.keys()
    assert "nvkey1" in cache.keys()


def test_session_clear():
    session = Session("test-session")
    session.set("key1", "value1")
    session.set("key2", "value2")
    session.get_volatile_cache().set("vkey1", "vvalue1")
    session.get_non_volatile_cache().set("nvkey1", "nvvalue1")
    session.clear()
    assert len(session.get_all_keys()) == 2
    assert session.get("key1") is None
    assert session.get("key2") is None
    assert len(session.get_volatile_cache().keys()) == 0
    assert session.get_volatile_cache().get("vkey1") is None
    assert len(session.get_non_volatile_cache().keys()) == 0
    assert session.get_non_volatile_cache().get("nvkey1") is None
