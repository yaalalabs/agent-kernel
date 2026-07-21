"""Shared helpers for pluggable-backend factories.

Every backend-selection factory (guardrail, trace, session store, …) resolves a config
``type`` to a class the same way: a curated set of built-ins via ``if/elif`` + real imports,
and any other value treated as a dotted path to a user-supplied subclass (bring-your-own).
These helpers centralize the two cross-cutting concerns of that shape — importing and
validating a dotted path, and turning a missing optional dependency into an actionable
message — plus the one typed error the factories raise.
"""

import importlib
from contextlib import contextmanager
from typing import Iterator, TypeVar

T = TypeVar("T")


class AKConfigError(Exception):
    """A configuration value could not be resolved to a usable backend.

    Raised for an unknown ``type``, a dotted path that cannot be imported, or a resolved
    object that is not the expected subclass.
    """


def resolve_dotted(path: str, *, base: type[T], error: type[Exception] = AKConfigError) -> type[T]:
    """Import a ``"pkg.module.ClassName"`` path and return the class.

    This is the bring-your-own hook: a config ``type`` that is not a built-in short name is
    treated as a dotted path to a ``base`` subclass. Any failure — not a dotted path,
    un-importable, missing attribute, or not a ``base`` subclass — raises ``error``, since a
    user-supplied path that does not resolve is a configuration error, not a crash.

    ``error`` defaults to ``AKConfigError``; callers with their own config-error type (e.g. the
    sandbox capability's ``SandboxConfigError``) pass it so the failure stays in their hierarchy.
    """
    module_path, _, attr = path.rpartition(".")
    if not module_path:
        raise error(f"'{path}' is not a dotted path to a {base.__name__} subclass")
    try:
        obj = getattr(importlib.import_module(module_path), attr)
    except (ImportError, AttributeError) as exc:
        raise error(f"could not import '{path}': {exc}") from exc
    if not (isinstance(obj, type) and issubclass(obj, base)):
        raise error(f"'{path}' is not a {base.__name__} subclass")
    return obj


@contextmanager
def require_extra(extra: str, feature: str) -> Iterator[None]:
    """Wrap a built-in backend import; on ``ImportError`` point at the pip extra that ships it.

    Use around the lazy import of a *built-in* backend whose SDK is an optional dependency::

        with require_extra("langfuse", "trace.type: langfuse"):
            from .langfuse.langfuse import LangFuse

    The error stays an ``ImportError`` (a genuinely missing dependency) rather than an
    ``AKConfigError`` (a misconfiguration).
    """
    try:
        yield
    except ImportError as exc:
        raise ImportError(f"{feature} requires the '{extra}' extra: pip install \"agentkernel[{extra}]\"") from exc
