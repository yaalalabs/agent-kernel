"""Core sandbox interfaces: the ``Sandbox`` handle and its ``SandboxProvider``.

Both are public ABCs — bring-your-own backends subclass them. The narrow required
surface (``execute_code`` with ``language="python"``, ``close``, ``create``,
``destroy``) is satisfiable by even the most constrained backends; every richer
operation is optional and, if not overridden, raises ``SandboxCapabilityError``
naming the missing capability.
"""

from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel

from .errors import SandboxCapabilityError
from .model import SandboxCapabilities, SandboxPolicy, SandboxPrincipal, SandboxResult


class Sandbox(ABC):
    """Handle to one live sandbox. Created by a ``SandboxProvider``, never constructed directly.

    Concurrency: a ``Sandbox`` instance is used only from the event loop that created it,
    with at most one in-flight execute call. Callers (``SandboxManager`` / broker worker)
    uphold this via a per-``sandbox_session_id`` lock; providers may assume it.
    """

    id: str  # provider-scoped identifier, stable across attach/reconnect

    @abstractmethod
    async def execute_code(self, code: str, language: str = "python", timeout: float | None = None) -> SandboxResult:
        """Run code and return a ``SandboxResult``.

        ``language="python"`` is mandatory for every provider. A failing *program*
        (compile error, exception, non-zero exit) is returned as a ``SandboxResult`` with
        ``exit_code != 0`` — not raised. Requesting an undeclared language raises
        ``SandboxCapabilityError`` naming the language.
        """

    async def execute_command(self, command: str, timeout: float | None = None) -> SandboxResult:
        raise SandboxCapabilityError(self.__class__.__name__, "shell")

    async def upload_file(self, path: str, content: bytes) -> None:
        raise SandboxCapabilityError(self.__class__.__name__, "files")

    async def download_file(self, path: str) -> bytes:
        raise SandboxCapabilityError(self.__class__.__name__, "files")

    async def install_packages(self, packages: list[str]) -> SandboxResult:
        raise SandboxCapabilityError(self.__class__.__name__, "package_install")

    @abstractmethod
    async def close(self) -> None:
        """Release the live handle. Idempotent.

        For ``per_session`` scope this must NOT destroy backend state needed for a later
        ``attach()`` — only ``destroy()`` permanently disposes backend state.
        """


class SandboxProvider(ABC):
    """One per configured profile backend. Constructed by the factory; long-lived.

    ``capabilities`` is declared honestly per provider (including a mandatory
    ``IsolationTier``) and is the single source of truth the manager/worker consult before
    routing an operation.
    """

    capabilities: ClassVar[SandboxCapabilities]

    def __init__(self, config: BaseModel) -> None:
        # Provider-specific Pydantic config sub-model, injected by the factory.
        # Providers never read AKConfig directly.
        self._config = config

    @abstractmethod
    async def create(self, *, principal: SandboxPrincipal, policy: SandboxPolicy) -> Sandbox:
        """Provision a new sandbox and return a live handle to it."""

    async def attach(self, sandbox_id: str, *, principal: SandboxPrincipal, policy: SandboxPolicy) -> Sandbox:
        """Reconnect to an existing sandbox.

        Raises ``SandboxGoneError`` when the backend reports the target as gone — the
        signal the manager/worker uses to self-heal by recreating under the same
        ``sandbox_session_id``.
        """
        raise SandboxCapabilityError(self.__class__.__name__, "attach")

    @abstractmethod
    async def destroy(self, sandbox_id: str) -> None:
        """Permanently dispose backend state. Idempotent; unknown ids are a no-op."""
