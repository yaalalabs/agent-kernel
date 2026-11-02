"""Network-free test for the session store selected by config.yaml.

This does not start the agent or call an LLM. It proves that the configured
backend stores a session and loads it back, which is the part this example is
about.
"""

from pathlib import Path

import pytest
from agentkernel.core.builder import SessionStoreBuilder
from agentkernel.core.config import AKConfig
from agentkernel.core.session.in_memory import InMemorySessionStore

EXAMPLE_DIR = Path(__file__).resolve().parent


@pytest.fixture(autouse=True)
def _use_example_config(monkeypatch):
    """Load this folder's config.yaml regardless of where pytest was started."""
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(EXAMPLE_DIR / "config.yaml"))
    AKConfig._reset()
    yield
    AKConfig._reset()


def test_configured_store_round_trips_a_session():
    store = SessionStoreBuilder.build()
    session = store.new("local-session-test")
    session.set("greeting", "hello from the configured store")
    store.store(session)

    reloaded = store.load("local-session-test", strict=True)
    assert reloaded.get("greeting") == "hello from the configured store"


def test_in_memory_store_does_not_survive_a_new_store():
    """Documents the trade-off: a fresh in_memory store starts empty.

    Uses `InMemorySessionStore` directly rather than `SessionStoreBuilder.build()`, since the
    configured backend in `config.yaml` may be a persistent one (Redis/Valkey) that this test
    should not require a running server for.
    """
    first = InMemorySessionStore()
    session = first.new("local-session-test")
    session.set("greeting", "hello")
    first.store(session)

    second = InMemorySessionStore()
    assert second.load("local-session-test").get("greeting") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
