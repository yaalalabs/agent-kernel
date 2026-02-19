import pytest

from agentkernel import Agent, Runner, Session
from agentkernel.core.builder import SessionStoreBuilder
from agentkernel.core.model import AgentReplyText, AgentRequestText
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.session.redis import RedisSessionStore


class DummyRunner(Runner):
    async def run(self, agent, session, requests):
        prompt = requests[0].text if isinstance(requests[0], AgentRequestText) else ""
        return AgentReplyText(text=f"ok:{prompt}")


class DummyAgent(Agent):

    def __init__(self, name):
        runner = DummyRunner("DummyRunner")
        super().__init__(name, runner)
        self._name = name

    @property
    def name(self):
        return self._name

    @property
    def runner(self):
        return self._runner

    def get_a2a_card(self):
        pass

    def get_description(self):
        pass

    def get_wrapped(self):
        return None

    def override_system_prompt(self, session, prompt):
        pass

    def attach_tool(self, tool):
        pass


def test_runtime_instance_redis_when_config(monkeypatch):
    class FakeCfg:
        class session:
            type = "redis"

            class redis:
                url = "redis://localhost:6379"
                ttl = 60
                prefix = "ak:test:"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    runtime = Runtime(SessionStoreBuilder.build())
    # Should select REDIS memory type and initialize a session store
    assert runtime.sessions() is not None
    assert type(runtime.sessions()) is RedisSessionStore


def test_runtime_instance_invalid_fallback(monkeypatch):
    class FakeCfg:
        class session:
            type = "not-a-real-type"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    runtime = Runtime(SessionStoreBuilder.build())
    assert runtime.sessions() is not None
    assert type(runtime.sessions()) is InMemorySessionStore

    # Should be able to register and list agents
    agent = DummyAgent("a1")
    runtime.register(agent)
    assert "a1" in runtime.agents()


@pytest.mark.asyncio
async def test_runtime_run_calls_runner(monkeypatch):
    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    runtime = Runtime(SessionStoreBuilder.build())
    agent = DummyAgent("agent")
    runtime.register(agent)
    session = runtime.sessions().new("s1")

    out = await runtime.run(agent, session, [AgentRequestText(text="ping")])
    assert out.text == "ok:ping"


@pytest.mark.asyncio
async def test_runtime_current_default(monkeypatch):
    """
    Test that Runtime.current() returns GlobalRuntime by default
    """

    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    from agentkernel.core.runtime import GlobalRuntime

    current_runtime = Runtime.current()
    assert current_runtime is not None
    assert isinstance(current_runtime, Runtime)
    # Should return GlobalRuntime singleton
    assert current_runtime == GlobalRuntime.instance()


@pytest.mark.asyncio
async def test_runtime_current_context_manager(monkeypatch):
    """
    Test that Runtime.current() returns the active runtime in a context manager
    """

    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    runtime = Runtime(SessionStoreBuilder.build())
    agent = DummyAgent("agent")

    # Before context, should get GlobalRuntime
    from agentkernel.core.runtime import GlobalRuntime

    before_runtime = Runtime.current()
    assert before_runtime == GlobalRuntime.instance()

    # Inside context, should get the specific runtime
    with runtime:
        current_runtime = Runtime.current()
        assert current_runtime is runtime
        assert current_runtime != GlobalRuntime.instance()

        # Register an agent and verify it works
        runtime.register(agent)
        assert "agent" in runtime.agents()

    # After context, should return to GlobalRuntime
    after_runtime = Runtime.current()
    assert after_runtime == GlobalRuntime.instance()


@pytest.mark.asyncio
async def test_auxiliary_cache_get_volatile_with_session_id(monkeypatch):
    """
    Test volatile cache access using Runtime.current().sessions().load() with explicit session_id
    """

    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    runtime = Runtime(SessionStoreBuilder.build())
    runtime.sessions().new("test-session-1")

    # Get volatile cache with explicit session_id using runtime.sessions().load()
    loaded_session = runtime.sessions().load("test-session-1")
    v_cache = loaded_session.get_volatile_cache()
    assert v_cache is not None

    # Set and get a value
    v_cache.set("test_key", "test_value")
    assert v_cache.get("test_key") == "test_value"


@pytest.mark.asyncio
async def test_auxiliary_cache_get_non_volatile_with_session_id(monkeypatch):
    """
    Test non-volatile cache access using Runtime.current().sessions().load() with explicit session_id
    """

    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    runtime = Runtime(SessionStoreBuilder.build())
    runtime.sessions().new("test-session-2")

    # Get non-volatile cache with explicit session_id using runtime.sessions().load()
    loaded_session = runtime.sessions().load("test-session-2")
    nv_cache = loaded_session.get_non_volatile_cache()
    assert nv_cache is not None

    # Set and get a value
    nv_cache.set("persistent_key", "persistent_value")
    assert nv_cache.get("persistent_key") == "persistent_value"


@pytest.mark.asyncio
async def test_auxiliary_cache_get_volatile_without_session_id_raises(monkeypatch):
    """
    Test that Session.current() returns None when no session context is available
    and accessing cache methods raises appropriate error
    """

    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    # Without setting session context, Session.current() should return None
    current_session = Session.current()
    assert current_session is None


@pytest.mark.asyncio
async def test_auxiliary_cache_get_non_volatile_without_session_id_raises(monkeypatch):
    """
    Test that Session.current() returns None when no session context is available
    and accessing cache methods raises appropriate error
    """

    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    # Without setting session context, Session.current() should return None
    current_session = Session.current()
    assert current_session is None

    # Attempting to access cache on None should raise AttributeError
    with pytest.raises(AttributeError):
        current_session.get_non_volatile_cache()


@pytest.mark.asyncio
async def test_auxiliary_cache_get_volatile_with_context_var(monkeypatch):
    """
    Test volatile cache access using Session.current() with context variable
    """

    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    runtime = Runtime(SessionStoreBuilder.build())
    with runtime:
        session = runtime.sessions().new("test-session-3")
        async with session:
            # Get volatile cache using Session.current()
            current_session = Session.current()
            v_cache = current_session.get_volatile_cache()
            assert v_cache is not None

            # Set value via cache
            v_cache.set("context_key", "context_value")

            # Verify the value is accessible
            assert v_cache.get("context_key") == "context_value"

            # Verify it's the same cache by checking the session's cache also has it
            assert session.get_volatile_cache().get("context_key") == "context_value"


@pytest.mark.asyncio
async def test_auxiliary_cache_get_non_volatile_with_context_var(monkeypatch):
    """
    Test non-volatile cache access using Session.current() with context variable
    """

    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    runtime = Runtime(SessionStoreBuilder.build())
    with runtime:
        session = runtime.sessions().new("test-session-4")
        async with session:
            # Get non-volatile cache using Session.current()
            current_session = Session.current()
            nv_cache = current_session.get_non_volatile_cache()
            assert nv_cache is not None

            # Set value via cache
            nv_cache.set("nv_context_key", "nv_context_value")

            # Verify the value is accessible
            assert nv_cache.get("nv_context_key") == "nv_context_value"

            # Verify it's the same cache by checking the session's cache also has it
            assert session.get_non_volatile_cache().get("nv_context_key") == "nv_context_value"


@pytest.mark.asyncio
async def test_auxiliary_cache_volatile_isolation_between_sessions(monkeypatch):
    """
    Test that volatile caches are isolated between different sessions
    """

    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    runtime = Runtime(SessionStoreBuilder.build())
    runtime.sessions().new("test-session-5")
    runtime.sessions().new("test-session-6")

    # Get caches for both sessions using runtime.sessions().load()
    loaded_session1 = runtime.sessions().load("test-session-5")
    loaded_session2 = runtime.sessions().load("test-session-6")
    v_cache1 = loaded_session1.get_volatile_cache()
    v_cache2 = loaded_session2.get_volatile_cache()

    # Set different values in each cache
    v_cache1.set("shared_key", "value_from_session1")
    v_cache2.set("shared_key", "value_from_session2")

    # Verify isolation
    assert v_cache1.get("shared_key") == "value_from_session1"
    assert v_cache2.get("shared_key") == "value_from_session2"


@pytest.mark.asyncio
async def test_auxiliary_cache_non_volatile_isolation_between_sessions(monkeypatch):
    """
    Test that non-volatile caches are isolated between different sessions
    """

    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    runtime = Runtime(SessionStoreBuilder.build())
    runtime.sessions().new("test-session-7")
    runtime.sessions().new("test-session-8")

    # Get caches for both sessions using runtime.sessions().load()
    loaded_session1 = runtime.sessions().load("test-session-7")
    loaded_session2 = runtime.sessions().load("test-session-8")
    nv_cache1 = loaded_session1.get_non_volatile_cache()
    nv_cache2 = loaded_session2.get_non_volatile_cache()

    # Set different values in each cache
    nv_cache1.set("shared_key", "nv_value_from_session1")
    nv_cache2.set("shared_key", "nv_value_from_session2")

    # Verify isolation
    assert nv_cache1.get("shared_key") == "nv_value_from_session1"
    assert nv_cache2.get("shared_key") == "nv_value_from_session2"


@pytest.mark.asyncio
async def test_auxiliary_cache_volatile_and_non_volatile_are_separate(monkeypatch):
    """
    Test that volatile and non-volatile caches are separate within same session
    """

    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    runtime = Runtime(SessionStoreBuilder.build())
    runtime.sessions().new("test-session-9")

    # Get both caches for the same session using runtime.sessions().load()
    loaded_session = runtime.sessions().load("test-session-9")
    v_cache = loaded_session.get_volatile_cache()
    nv_cache = loaded_session.get_non_volatile_cache()

    # Set same key in both caches with different values
    v_cache.set("common_key", "volatile_value")
    nv_cache.set("common_key", "non_volatile_value")

    # Verify they are separate
    assert v_cache.get("common_key") == "volatile_value"
    assert nv_cache.get("common_key") == "non_volatile_value"


@pytest.mark.asyncio
async def test_auxiliary_cache_operations_on_volatile_cache(monkeypatch):
    """
    Test various operations on volatile cache through direct session access
    """

    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    runtime = Runtime(SessionStoreBuilder.build())
    runtime.sessions().new("test-session-10")

    # Get volatile cache using runtime.sessions().load()
    loaded_session = runtime.sessions().load("test-session-10")
    v_cache = loaded_session.get_volatile_cache()

    # Test set and get
    v_cache.set("key1", "value1")
    assert v_cache.get("key1") == "value1"

    # Test has
    assert v_cache.has("key1") is True
    assert v_cache.has("nonexistent") is False

    # Test get with default
    assert v_cache.get("nonexistent", "default") == "default"

    # Test keys
    v_cache.set("key2", "value2")
    keys = v_cache.keys()
    assert "key1" in keys
    assert "key2" in keys

    # Test delete
    v_cache.delete("key1")
    assert v_cache.has("key1") is False
    assert v_cache.has("key2") is True

    # Test clear
    v_cache.clear()
    assert len(v_cache.keys()) == 0


@pytest.mark.asyncio
async def test_auxiliary_cache_operations_on_non_volatile_cache(monkeypatch):
    """
    Test various operations on non-volatile cache through direct session access
    """

    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    runtime = Runtime(SessionStoreBuilder.build())
    runtime.sessions().new("test-session-11")

    # Get non-volatile cache using runtime.sessions().load()
    loaded_session = runtime.sessions().load("test-session-11")
    nv_cache = loaded_session.get_non_volatile_cache()

    # Test set and get
    nv_cache.set("key1", "value1")
    assert nv_cache.get("key1") == "value1"

    # Test has
    assert nv_cache.has("key1") is True
    assert nv_cache.has("nonexistent") is False

    # Test get with default
    assert nv_cache.get("nonexistent", "default") == "default"

    # Test keys
    nv_cache.set("key2", "value2")
    keys = nv_cache.keys()
    assert "key1" in keys
    assert "key2" in keys

    # Test delete
    nv_cache.delete("key1")
    assert nv_cache.has("key1") is False
    assert nv_cache.has("key2") is True

    # Test clear
    nv_cache.clear()
    assert len(nv_cache.keys()) == 0


@pytest.mark.asyncio
async def test_auxiliary_cache_with_complex_data_types(monkeypatch):
    """
    Test cache with various complex data types
    """

    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    runtime = Runtime(SessionStoreBuilder.build())
    runtime.sessions().new("test-session-12")

    # Get volatile cache using runtime.sessions().load()
    loaded_session = runtime.sessions().load("test-session-12")
    v_cache = loaded_session.get_volatile_cache()

    # Test with dict
    test_dict = {"name": "test", "value": 123}
    v_cache.set("dict_key", test_dict)
    assert v_cache.get("dict_key") == test_dict

    # Test with list
    test_list = [1, 2, 3, "four"]
    v_cache.set("list_key", test_list)
    assert v_cache.get("list_key") == test_list

    # Test with nested structures
    nested_data = {"level1": {"level2": {"items": [1, 2, 3], "metadata": {"count": 3}}}}
    v_cache.set("nested_key", nested_data)
    assert v_cache.get("nested_key") == nested_data


@pytest.mark.asyncio
async def test_load_empty_session_id_creates_session(monkeypatch):
    """
    Test that empty string session_id creates a new session
    """

    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    runtime = Runtime(SessionStoreBuilder.build())

    # Empty string session_id should create a new session
    loaded_session = runtime.sessions().load("")
    assert loaded_session is not None
    assert loaded_session.id == ""


@pytest.mark.asyncio
async def test_deprecated_auxiliary_cache_matches_new_method_with_session_id(monkeypatch):
    """
    Test that deprecated AuxiliaryCache.get_volatile_cache() returns the same cache as the new method
    when using explicit session_id
    """

    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    from agentkernel.core.runtime import AuxiliaryCache

    runtime = Runtime(SessionStoreBuilder.build())
    with runtime:
        runtime.sessions().new("test-session-verify-1")

        # Get cache using deprecated method
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            cache_old = AuxiliaryCache.get_volatile_cache(session_id="test-session-verify-1")
            cache_old.set("key1", "value1")

        # Get cache using new method
        cache_new = Runtime.current().sessions().load("test-session-verify-1").get_volatile_cache()

        # Verify they access the same underlying cache
        assert cache_new.get("key1") == "value1"
        cache_new.set("key2", "value2")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            assert cache_old.get("key2") == "value2"


@pytest.mark.asyncio
async def test_deprecated_auxiliary_cache_matches_new_method_current_session(monkeypatch):
    """
    Test that deprecated AuxiliaryCache.get_volatile_cache() returns the same cache as the new method
    when using current session context
    """

    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    from agentkernel.core.runtime import AuxiliaryCache

    runtime = Runtime(SessionStoreBuilder.build())
    with runtime:
        session = runtime.sessions().new("test-session-verify-2")
        async with session:
            # Get cache using deprecated method
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                cache_old = AuxiliaryCache.get_volatile_cache()
                cache_old.set("ctx_key1", "ctx_value1")

            # Get cache using new method
            cache_new = Session.current().get_volatile_cache()

            # Verify they access the same underlying cache
            assert cache_new.get("ctx_key1") == "ctx_value1"
            cache_new.set("ctx_key2", "ctx_value2")

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                assert cache_old.get("ctx_key2") == "ctx_value2"


@pytest.mark.asyncio
async def test_deprecated_auxiliary_cache_non_volatile_matches_new_method(monkeypatch):
    """
    Test that deprecated AuxiliaryCache.get_non_volatile_cache() returns the same cache as the new method
    """

    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    from agentkernel.core.runtime import AuxiliaryCache

    runtime = Runtime(SessionStoreBuilder.build())
    with runtime:
        runtime.sessions().new("test-session-verify-3")

        # Get cache using deprecated method
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            nv_cache_old = AuxiliaryCache.get_non_volatile_cache(session_id="test-session-verify-3")
            nv_cache_old.set("nv_key1", "nv_value1")

        # Get cache using new method
        nv_cache_new = Runtime.current().sessions().load("test-session-verify-3").get_non_volatile_cache()

        # Verify they access the same underlying cache
        assert nv_cache_new.get("nv_key1") == "nv_value1"
        nv_cache_new.set("nv_key2", "nv_value2")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            assert nv_cache_old.get("nv_key2") == "nv_value2"
