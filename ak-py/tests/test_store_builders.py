"""Phase-2 tests: session / thread / multimodal storage factories on the shared pattern.

Covers the behaviour change (unknown type now fails loud instead of silently falling back to
an in-memory default) and the bring-your-own dotted-path hatch with each surface's
construction contract (session store gets ``cache=``, thread store is no-arg, attachment store
gets ``session_id``).
"""

import sys
import types
from unittest.mock import Mock, patch

import pytest

from agentkernel.core.builder import SessionStoreBuilder
from agentkernel.core.config import AKConfig, _ThreadValkeyConfig
from agentkernel.core.multimodal.storage.base import AttachmentStore
from agentkernel.core.multimodal.storage.in_memory import InMemoryAttachmentStore
from agentkernel.core.multimodal.storage.storage_manager import AttachmentStorageManager
from agentkernel.core.session.base import SessionStore
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.thread.store.base import _BUILTIN_THREAD_STORES, ThreadStore, ThreadStoreBuilder
from agentkernel.core.thread.store.in_memory import InMemoryThreadStore
from agentkernel.core.thread.store.valkey import ValkeyThreadStore
from agentkernel.core.util.factory import AKConfigError


def _patch_import(monkeypatch, module_name, namespace):
    """Make resolve_dotted's importlib return `namespace` for `module_name`."""
    import agentkernel.core.util.factory as fac

    real = fac.importlib.import_module
    monkeypatch.setattr(
        fac.importlib,
        "import_module",
        lambda name, *a, **k: namespace if name == module_name else real(name, *a, **k),
    )


# --- bring-your-own test doubles (each subclasses the real ABC) ------------- #


class _ByoSessionStore(SessionStore):
    def __init__(self, cache=None):
        self.cache = cache

    def new(self, session_id): ...

    def load(self, session_id, strict=False): ...

    def store(self, session): ...

    def clear(self): ...


class _ByoThreadStore(ThreadStore):
    def create(self, thread): ...

    def update_name(self, session_id, name): ...

    def load_metadata(self, session_id): ...

    def append_message(self, session_id, message): ...

    def get_messages(self, session_id, limit, offset=0): ...

    def list_threads(self, *args, **kwargs): ...

    def clear(self): ...


class _ByoAttachmentStore(AttachmentStore):
    def __init__(self, session_id):
        self.session_id = session_id

    def save(self, attachment, max_attachments): ...

    def get(self, attachment_id): ...

    def delete(self, attachment_id): ...


# --- SessionStoreBuilder ---------------------------------------------------- #


def test_session_builder_default_in_memory():
    with patch.object(AKConfig, "get") as mock_get:
        cfg = Mock()
        cfg.session.type = "in_memory"
        cfg.session.cache = None
        mock_get.return_value = cfg
        assert isinstance(SessionStoreBuilder.build(), InMemorySessionStore)


def test_session_builder_unknown_type_fails_loud():
    with patch.object(AKConfig, "get") as mock_get:
        cfg = Mock()
        cfg.session.type = "reids"  # typo -> no longer a silent fallback to in_memory
        cfg.session.cache = None
        mock_get.return_value = cfg
        with pytest.raises(AKConfigError):
            SessionStoreBuilder.build()


def test_session_builder_byo_dotted_path_gets_cache(monkeypatch):
    _patch_import(monkeypatch, "byo_pkg", types.SimpleNamespace(Store=_ByoSessionStore))
    with patch.object(AKConfig, "get") as mock_get:
        cfg = Mock()
        cfg.session.type = "byo_pkg.Store"
        cfg.session.cache = None
        mock_get.return_value = cfg
        store = SessionStoreBuilder.build()
    assert isinstance(store, _ByoSessionStore)
    assert store.cache is None  # builder passed cache= per the session contract


# --- ThreadStoreBuilder ----------------------------------------------------- #


def test_thread_builder_default_memory():
    with patch.object(AKConfig, "get") as mock_get:
        cfg = Mock()
        cfg.thread.type = "memory"
        mock_get.return_value = cfg
        assert isinstance(ThreadStoreBuilder.build(), InMemoryThreadStore)


def test_thread_builder_unknown_type_fails_loud():
    with patch.object(AKConfig, "get") as mock_get:
        cfg = Mock()
        cfg.thread.type = "bogus"
        mock_get.return_value = cfg
        with pytest.raises(AKConfigError):
            ThreadStoreBuilder.build()


def test_thread_builder_not_configured_raises_value_error():
    with patch.object(AKConfig, "get") as mock_get:
        cfg = Mock()
        cfg.thread = None
        mock_get.return_value = cfg
        with pytest.raises(ValueError):
            ThreadStoreBuilder.build()


def test_thread_builder_byo_dotted_path(monkeypatch):
    _patch_import(monkeypatch, "byo_pkg", types.SimpleNamespace(Store=_ByoThreadStore))
    with patch.object(AKConfig, "get") as mock_get:
        cfg = Mock()
        cfg.thread.type = "byo_pkg.Store"
        mock_get.return_value = cfg
        assert isinstance(ThreadStoreBuilder.build(), _ByoThreadStore)


def test_thread_builder_valkey():
    # A real _ThreadValkeyConfig, not a Mock attribute: ValkeyThreadStore reads
    # url/prefix/ttl off it and int(Mock()) would raise.
    with patch.object(AKConfig, "get") as mock_get:
        cfg = Mock()
        cfg.thread.type = "valkey"
        cfg.thread.valkey = _ThreadValkeyConfig()
        mock_get.return_value = cfg
        assert isinstance(ThreadStoreBuilder.build(), ValkeyThreadStore)


def test_thread_builder_valkey_missing_extra_points_at_pip_extra(monkeypatch):
    # Poisoning sys.modules with None makes the branch's `from .valkey import ...`
    # raise ImportError, which require_extra should rewrite with an install hint.
    monkeypatch.setitem(sys.modules, "agentkernel.core.thread.store.valkey", None)
    with patch.object(AKConfig, "get") as mock_get:
        cfg = Mock()
        cfg.thread.type = "valkey"
        mock_get.return_value = cfg
        with pytest.raises(ImportError) as exc_info:
            ThreadStoreBuilder.build()
    assert 'pip install "agentkernel[valkey]"' in str(exc_info.value)


def test_builtin_thread_stores_lists_valkey_for_the_unknown_type_error():
    # The unknown-type AKConfigError names this list, so it is user-facing.
    assert "valkey" in _BUILTIN_THREAD_STORES


# --- multimodal attachment storage ----------------------------------------- #


def test_multimodal_default_in_memory():
    with patch.object(AKConfig, "get") as mock_get:
        cfg = Mock()
        cfg.multimodal.storage_type = "in_memory"
        mock_get.return_value = cfg
        assert isinstance(AttachmentStorageManager._build_driver("sess-1"), InMemoryAttachmentStore)


def test_multimodal_unknown_type_fails_loud():
    with patch.object(AKConfig, "get") as mock_get:
        cfg = Mock()
        cfg.multimodal.storage_type = "reids"
        mock_get.return_value = cfg
        with pytest.raises(AKConfigError):
            AttachmentStorageManager._build_driver("sess-1")


def test_multimodal_byo_dotted_path_gets_session_id(monkeypatch):
    _patch_import(monkeypatch, "byo_pkg", types.SimpleNamespace(Store=_ByoAttachmentStore))
    with patch.object(AKConfig, "get") as mock_get:
        cfg = Mock()
        cfg.multimodal.storage_type = "byo_pkg.Store"
        mock_get.return_value = cfg
        store = AttachmentStorageManager._build_driver("sess-1")
    assert isinstance(store, _ByoAttachmentStore)
    assert store.session_id == "sess-1"  # builder passed session_id per the multimodal contract
