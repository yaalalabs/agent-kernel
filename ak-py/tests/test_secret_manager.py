import threading
import time

import pytest
from pydantic import ValidationError

from agentkernel.core.config import AKConfig, _SecretConfig
from agentkernel.core.util.factory import AKConfigError
from agentkernel.secret import EnvSecretProvider, SecretCache, SecretError, SecretManager, SecretNotFoundError, SecretProvider
from agentkernel.secret import cache as cache_module

KEY = "OPENAI_API_KEY"


class _DictSecretProvider(SecretProvider):
    """A seedable, Lock-guarded dict that records every key it is asked for.

    `hook`, when set, runs inside get_secret before the lookup — the concurrency tests use it to
    sleep or park on an Event while the provider call is in flight.
    """

    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._lock = threading.Lock()
        self.calls: list[str] = []
        self.hook = None

    def seed(self, key: str, value: str) -> None:
        with self._lock:
            self._values[key] = value

    def get_secret(self, key):
        with self._lock:
            self.calls.append(key)
        if self.hook is not None:
            self.hook(key)
        with self._lock:
            return self._values.get(key)


# Built from __name__ so the path resolves however pytest imported this module.
_DICT_PROVIDER = f"{__name__}._DictSecretProvider"


class _FailingSecretProvider(SecretProvider):
    def get_secret(self, key):
        raise SecretError(f"backend failed for '{key}'")


class _FakeClock:
    """A monkeypatchable stand-in for time.monotonic."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def _reset_manager(monkeypatch):
    monkeypatch.delenv(KEY, raising=False)
    SecretManager.reset()
    yield
    SecretManager.reset()


@pytest.fixture
def provider():
    return _DictSecretProvider()


@pytest.fixture
def manager(provider):
    return SecretManager(provider=provider, cache_ttl=300)


@pytest.fixture
def clock(monkeypatch):
    fake = _FakeClock()
    monkeypatch.setattr(cache_module.time, "monotonic", fake)
    return fake


def _configure_secret(monkeypatch, **secret_fields) -> None:
    """Point AKConfig at a secret block built from `secret_fields`."""
    AKConfig._reset()
    base = AKConfig.get()
    secret = _SecretConfig.model_validate(secret_fields)
    monkeypatch.setattr(AKConfig, "get", classmethod(lambda cls: base.model_copy(update={"secret": secret})))


# -- resolution order ----------------------------------------------------------------------


def test_environment_wins_over_cache_and_provider(monkeypatch, manager, provider):
    provider.seed(KEY, "from-provider")
    assert manager.get(KEY) == "from-provider"  # now cached
    provider.calls.clear()

    monkeypatch.setenv(KEY, "from-env")
    assert manager.get(KEY) == "from-env"
    assert provider.calls == []


def test_cache_hit_does_not_call_provider(manager, provider):
    provider.seed(KEY, "v")
    assert manager.get(KEY) == "v"
    assert manager.get(KEY) == "v"
    assert provider.calls == [KEY]


def test_provider_called_when_environment_and_cache_miss(manager, provider):
    provider.seed(KEY, "v")
    assert manager.get(KEY) == "v"
    assert provider.calls == [KEY]


def test_empty_environment_variable_is_a_miss(monkeypatch, manager, provider):
    monkeypatch.setenv(KEY, "")
    provider.seed(KEY, "from-provider")
    assert manager.get(KEY) == "from-provider"
    assert provider.calls == [KEY]


def test_environment_hits_are_not_cached(monkeypatch, manager, provider):
    monkeypatch.setenv(KEY, "from-env")
    assert manager.get(KEY) == "from-env"
    monkeypatch.delenv(KEY)

    with pytest.raises(SecretNotFoundError):
        manager.get(KEY)
    provider.seed(KEY, "from-provider")
    assert manager.get(KEY) == "from-provider"


def test_variable_set_after_cached_hit_wins(monkeypatch, manager, provider):
    provider.seed(KEY, "from-provider")
    assert manager.get(KEY) == "from-provider"
    monkeypatch.setenv(KEY, "from-env")
    assert manager.get(KEY) == "from-env"


def test_key_is_carried_through_unchanged(monkeypatch, manager, provider):
    seen_env_keys = []
    real_get = cache_module.SecretCache.get

    def recording_get(self, key):
        seen_env_keys.append(key)
        return real_get(self, key)

    monkeypatch.setattr(cache_module.SecretCache, "get", recording_get)
    provider.seed(KEY, "v")

    assert manager.get(KEY) == "v"
    assert provider.calls == [KEY]
    assert seen_env_keys == [KEY]
    assert list(manager._cache._entries) == [KEY]
    monkeypatch.setenv(KEY, "env")
    assert manager.get(KEY) == "env"  # layer 1 reads os.environ under the same key


def test_environment_only_under_env_provider(monkeypatch):
    manager = SecretManager(provider=EnvSecretProvider())
    monkeypatch.setenv(KEY, "from-env")
    assert manager.get(KEY) == "from-env"
    monkeypatch.delenv(KEY)
    with pytest.raises(SecretNotFoundError):
        manager.get(KEY)
    assert manager._cache._entries == {}


# -- misses, defaults, failures ------------------------------------------------------------


def test_provider_hit_is_cached_but_miss_is_not(manager, provider):
    with pytest.raises(SecretNotFoundError):
        manager.get(KEY)
    provider.seed(KEY, "v")
    assert manager.get(KEY) == "v"
    assert provider.calls == [KEY, KEY]


def test_total_miss_raises_naming_key_not_value(manager, provider):
    provider.seed("OTHER_KEY", "s3cr3t-value")
    with pytest.raises(SecretNotFoundError) as exc_info:
        manager.get(KEY)
    assert exc_info.value.key == KEY
    assert KEY in str(exc_info.value)
    assert "s3cr3t-value" not in str(exc_info.value)


def test_not_found_is_a_secret_error():
    assert issubclass(SecretNotFoundError, SecretError)


def test_default_returned_on_miss(manager):
    assert manager.get(KEY, default="x") == "x"


def test_default_none_returns_none_rather_than_raising(manager):
    assert manager.get(KEY, default=None) is None


def test_provider_failure_is_not_masked_by_default():
    manager = SecretManager(provider=_FailingSecretProvider())
    with pytest.raises(SecretError):
        manager.get(KEY, default="x")
    assert manager._cache._entries == {}


def test_get_never_writes_environment(monkeypatch, manager, provider):
    import os

    provider.seed(KEY, "v")
    assert manager.get(KEY) == "v"
    assert KEY not in os.environ

    monkeypatch.setenv("EMPTY_KEY", "")
    provider.seed("EMPTY_KEY", "v2")
    assert manager.get("EMPTY_KEY") == "v2"
    assert os.environ["EMPTY_KEY"] == ""

    assert not hasattr(SecretManager, "inject")


# -- key grammar ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_key", ["openai_api_key", "Mixed_Case", "BAD-KEY", "1BAD", "BAD/KEY", "A B", "A=B", "", "KEY\n", " KEY", "KEY "])
def test_malformed_key_rejected_before_any_layer(monkeypatch, manager, provider, bad_key):
    import os

    before = dict(os.environ)
    with pytest.raises(ValueError):
        manager.get(bad_key)
    with pytest.raises(ValueError):
        manager.invalidate(bad_key)
    assert provider.calls == []
    assert dict(os.environ) == before


# -- cache TTL -----------------------------------------------------------------------------


def test_positive_ttl_serves_from_cache_then_re_resolves(clock, provider):
    manager = SecretManager(provider=provider, cache_ttl=60)
    provider.seed(KEY, "v1")
    assert manager.get(KEY) == "v1"

    provider.seed(KEY, "v2")
    clock.now += 59
    assert manager.get(KEY) == "v1"
    clock.now += 1
    assert manager.get(KEY) == "v2"
    assert provider.calls == [KEY, KEY]


def test_zero_ttl_re_resolves_every_call(provider):
    manager = SecretManager(provider=provider, cache_ttl=0)
    provider.seed(KEY, "v")
    assert manager.get(KEY) == "v"
    assert manager.get(KEY) == "v"
    assert provider.calls == [KEY, KEY]
    manager.invalidate(KEY)
    manager.clear()
    assert not manager._cache.enabled


def test_negative_ttl_raises_config_error(provider):
    with pytest.raises(AKConfigError):
        SecretManager(provider=provider, cache_ttl=-1)
    with pytest.raises(AKConfigError):
        SecretCache(-1)


def test_negative_ttl_in_model_raises_validation_error():
    with pytest.raises(ValidationError):
        _SecretConfig.model_validate({"cache_ttl": -1})


# -- invalidate / clear --------------------------------------------------------------------


def test_invalidate_drops_one_entry(manager, provider):
    provider.seed(KEY, "v")
    provider.seed("OTHER_KEY", "o")
    manager.get(KEY)
    manager.get("OTHER_KEY")
    provider.calls.clear()

    manager.invalidate(KEY)
    assert provider.calls == []  # invalidate never touches the provider
    manager.get(KEY)
    manager.get("OTHER_KEY")
    assert provider.calls == [KEY]


def test_clear_drops_all_entries(manager, provider):
    provider.seed(KEY, "v")
    provider.seed("OTHER_KEY", "o")
    manager.get(KEY)
    manager.get("OTHER_KEY")
    provider.calls.clear()

    manager.clear()
    assert provider.calls == []
    manager.get(KEY)
    manager.get("OTHER_KEY")
    assert sorted(provider.calls) == sorted([KEY, "OTHER_KEY"])


def test_invalidate_and_clear_do_not_touch_environment(monkeypatch, manager):
    monkeypatch.setenv(KEY, "from-env")
    manager.invalidate(KEY)
    manager.clear()
    assert manager.get(KEY) == "from-env"


def test_invalidate_and_clear_on_unknown_key_do_not_raise(manager):
    manager.invalidate("NEVER_SEEN")
    manager.clear()


# -- concurrency ---------------------------------------------------------------------------


def test_concurrent_cold_reads_are_correct(manager, provider):
    provider.seed(KEY, "v")
    provider.hook = lambda key: time.sleep(0.02)
    results = []
    start = threading.Barrier(8)

    def worker():
        start.wait()
        results.append(manager.get(KEY))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert results == ["v"] * 8
    assert 1 <= len(provider.calls) <= 8


def test_provider_call_holds_no_lock(monkeypatch, manager, provider):
    entered = threading.Event()
    release = threading.Event()
    provider.seed("KEY_A", "a")
    provider.seed("KEY_B", "b")
    manager.get("KEY_B")  # cached
    monkeypatch.setenv("KEY_C", "c")

    def park(key):
        if key == "KEY_A":
            entered.set()
            release.wait(timeout=5)

    provider.hook = park
    parked = threading.Thread(target=manager.get, args=("KEY_A",))
    parked.start()
    try:
        assert entered.wait(timeout=5)
        others = {}

        def others_worker():
            others["b"] = manager.get("KEY_B")
            others["c"] = manager.get("KEY_C")
            manager.invalidate("KEY_B")
            manager.clear()
            others["done"] = True

        t = threading.Thread(target=others_worker)
        t.start()
        t.join(timeout=2)
        assert others == {"b": "b", "c": "c", "done": True}
    finally:
        release.set()
        parked.join(timeout=5)


def test_reentrant_provider_does_not_deadlock(monkeypatch):
    monkeypatch.setenv("INNER_CREDENTIAL", "cred")

    class _ReentrantProvider(SecretProvider):
        def get_secret(self, key):
            return f"{key}:{SecretManager.current().get('INNER_CREDENTIAL')}"

    _configure_secret(monkeypatch)
    outer = SecretManager.current()
    outer._provider = _ReentrantProvider()

    result = {}
    t = threading.Thread(target=lambda: result.setdefault("v", outer.get(KEY)))
    t.start()
    t.join(timeout=5)
    assert result == {"v": f"{KEY}:cred"}


def test_cache_eviction_never_drops_a_fresh_entry(monkeypatch, clock):
    cache = SecretCache(10)
    cache.set(KEY, "old")
    clock.now += 10  # expired

    real_lock = cache._lock

    class _SetBeforeEvict:
        """Lets a concurrent set land between get's expired read and its eviction."""

        def __enter__(self):
            cache._lock = real_lock
            cache.set(KEY, "fresh")
            real_lock.acquire()

        def __exit__(self, *exc):
            real_lock.release()

    cache._lock = _SetBeforeEvict()
    assert cache.get(KEY) is None  # the read saw the expired tuple
    assert cache.get(KEY) == "fresh"  # the concurrent set survived eviction


# -- singleton -----------------------------------------------------------------------------


def test_current_is_a_singleton_built_from_config(monkeypatch):
    _configure_secret(monkeypatch, provider={"type": _DICT_PROVIDER}, cache_ttl=7)
    first = SecretManager.current()
    assert SecretManager.current() is first
    assert isinstance(first._provider, _DictSecretProvider)
    assert first._cache._ttl == 7

    SecretManager.reset()
    assert SecretManager.current() is not first


def test_current_defaults_to_env_provider(monkeypatch):
    _configure_secret(monkeypatch)
    assert isinstance(SecretManager.current()._provider, EnvSecretProvider)
