"""Tests for the shared pluggable-backend factory helpers (core/util/factory.py)."""

import pytest

from agentkernel.core.util.factory import AKConfigError, require_extra, resolve_dotted
from agentkernel.guardrail.guardrail import InputGuardrail
from agentkernel.guardrail.openai import OpenAIInputGuardrail


def test_resolve_dotted_resolves_subclass():
    cls = resolve_dotted("agentkernel.guardrail.openai.OpenAIInputGuardrail", base=InputGuardrail)
    assert cls is OpenAIInputGuardrail


def test_resolve_dotted_not_a_dotted_path():
    with pytest.raises(AKConfigError):
        resolve_dotted("nodots", base=object)


def test_resolve_dotted_unimportable_module():
    with pytest.raises(AKConfigError):
        resolve_dotted("agentkernel.no_such_module_xyz.Thing", base=object)


def test_resolve_dotted_missing_attribute():
    with pytest.raises(AKConfigError):
        resolve_dotted("agentkernel.guardrail.openai.NoSuchClass", base=InputGuardrail)


def test_resolve_dotted_not_a_subclass():
    with pytest.raises(AKConfigError):
        resolve_dotted("builtins.str", base=InputGuardrail)


def test_require_extra_wraps_import_error_with_install_hint():
    with pytest.raises(ImportError) as exc_info:
        with require_extra("langfuse", "trace.type: langfuse"):
            raise ImportError("No module named 'langfuse'")
    message = str(exc_info.value)
    assert "trace.type: langfuse" in message
    assert "agentkernel[langfuse]" in message


def test_require_extra_passes_through_success():
    ran = False
    with require_extra("langfuse", "trace.type: langfuse"):
        ran = True
    assert ran


def test_require_extra_only_catches_import_error():
    # A non-ImportError inside the block propagates unchanged.
    with pytest.raises(ValueError):
        with require_extra("langfuse", "trace.type: langfuse"):
            raise ValueError("unrelated")
