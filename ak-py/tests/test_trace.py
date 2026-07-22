"""Tests for the trace factory's backend resolution (trace/trace.py)."""

import sys
import types
from unittest.mock import Mock, patch

import pytest

from agentkernel.core.config import AKConfig
from agentkernel.core.util.factory import AKConfigError
from agentkernel.trace.base import BaseTrace
from agentkernel.trace.trace import Trace


class _FakeTrace(BaseTrace):
    """Minimal BYO tracer implementing the full BaseTrace surface."""

    def __init__(self):
        self.inited = False

    def init(self):
        self.inited = True

    def openai(self):
        return None

    def langgraph(self):
        return None

    def crewai(self):
        return None

    def adk(self):
        return None

    def smolagents(self):
        return None

    def pydanticai(self):
        return None


def _config(enabled, type_=None):
    cfg = Mock()
    cfg.trace.enabled = enabled
    cfg.trace.type = type_
    return cfg


def test_trace_disabled_returns_null_wrapper():
    with patch.object(AKConfig, "get", return_value=_config(False)):
        trace = Trace.get()
    assert trace._instance is None
    assert trace.openai() is None  # delegates to nothing when disabled


def test_trace_unknown_type_raises_akconfigerror():
    with patch.object(AKConfig, "get", return_value=_config(True, "bogus")):
        with pytest.raises(AKConfigError) as exc_info:
            Trace.get()
    assert "bogus" in str(exc_info.value)


def test_trace_byo_dotted_path(monkeypatch):
    import agentkernel.core.util.factory as fac

    monkeypatch.setattr(
        fac.importlib,
        "import_module",
        lambda name: types.SimpleNamespace(FakeTrace=_FakeTrace) if name == "acme_obs" else __import__(name),
    )
    with patch.object(AKConfig, "get", return_value=_config(True, "acme_obs.FakeTrace")):
        trace = Trace.get()
    assert isinstance(trace._instance, _FakeTrace)
    assert trace._instance.inited is True  # Trace.get() calls init()


def test_trace_byo_non_subclass_rejected():
    with patch.object(AKConfig, "get", return_value=_config(True, "builtins.str")):
        with pytest.raises(AKConfigError):
            Trace.get()


def test_trace_langfuse_missing_extra_raises_friendly_import_error(monkeypatch):
    """The langfuse built-in routes its import through require_extra: a missing SDK yields the
    friendly `agentkernel[langfuse]` message, not a bare ImportError."""
    monkeypatch.setitem(sys.modules, "langfuse", None)  # simulate the SDK not installed
    with patch.object(AKConfig, "get", return_value=_config(True, "langfuse")):
        with pytest.raises(ImportError) as exc_info:
            Trace.get()
    assert "agentkernel[langfuse]" in str(exc_info.value)


def test_trace_openllmetry_missing_extra_raises_friendly_import_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "traceloop", None)
    monkeypatch.setitem(sys.modules, "traceloop.sdk", None)
    with patch.object(AKConfig, "get", return_value=_config(True, "openllmetry")):
        with pytest.raises(ImportError) as exc_info:
            Trace.get()
    assert "agentkernel[openllmetry]" in str(exc_info.value)
