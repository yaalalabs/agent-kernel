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

from .errors import SandboxCapabilityError, SandboxConfigError
from .model import SandboxCapabilities, SandboxPolicy, SandboxPrincipal, SandboxResult


class Sandbox(ABC):
    """Handle to one live sandbox. Created by a ``SandboxProvider``, never constructed directly.

    Concurrency: a ``Sandbox`` instance is used only from the event loop that created it,
    with at most one in-flight execute call. Callers (``ExecutionManager`` / broker worker)
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
        """Run a shell command and return a ``SandboxResult``.

        Optional: override only when the provider declares ``capabilities.shell``; the
        default raises ``SandboxCapabilityError``.
        """
        raise SandboxCapabilityError(self.__class__.__name__, "shell")

    async def upload_file(self, path: str, content: bytes) -> None:
        """Write ``content`` to ``path`` inside the sandbox workspace.

        Optional: override only when the provider declares ``capabilities.files``; the
        default raises ``SandboxCapabilityError``.
        """
        raise SandboxCapabilityError(self.__class__.__name__, "files")

    async def download_file(self, path: str) -> bytes:
        """Read and return the bytes at ``path`` inside the sandbox workspace.

        Optional: override only when the provider declares ``capabilities.files``; the
        default raises ``SandboxCapabilityError``.
        """
        raise SandboxCapabilityError(self.__class__.__name__, "files")

    async def install_packages(self, packages: list[str]) -> SandboxResult:
        """Install packages into the sandbox and return the installer's ``SandboxResult``.

        Optional: override only when the provider declares ``capabilities.package_install``;
        the default raises ``SandboxCapabilityError``.
        """
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
        """Store the provider-specific Pydantic config sub-model, injected by the factory.

        Providers never read ``AKConfig`` directly.
        """
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


class AttachedEnvironment(Sandbox):
    """Handle to an environment the framework connects to but never owns.

    The handle counterpart of ``AttachedEnvironmentProvider``: where a ``Sandbox`` handle
    fronts something the provider created (and will eventually destroy), an ``AttachedEnvironment``
    fronts something that already exists independently — an EC2 instance, a running pod, a
    production service. Concrete attach-only handles subclass this instead of ``Sandbox``
    so their names stop claiming sandbox-ness (e.g. ``EC2SSMEnvironment``).

    The one lifecycle rule it fixes: ``close()`` is a no-op — releasing the handle must
    never affect an environment that runs independently of the framework.
    """

    async def close(self) -> None:
        """Nothing to release — the environment runs independently of the framework. Idempotent."""
        return None


class AttachedEnvironmentProvider(SandboxProvider):
    """Base for attach-only providers: environments the framework connects to but never owns.

    Subclasses bind to something that already exists (an EC2 instance, a running pod, a
    production service) and therefore implement only ``attach``, returning an
    ``AttachedEnvironment`` handle. This base fixes the lifecycle non-ownership once: ``create``
    binds to the configured ``attach_to`` target (never provisions) and ``destroy`` is a
    no-op (never disposes). Declare ``provisions=False`` and ``attaches_external=True`` in
    ``capabilities``; profiles selecting such a provider must opt in with
    ``environment: attached``.
    """

    async def create(self, *, principal: SandboxPrincipal, policy: SandboxPolicy) -> Sandbox:
        """Bind to the configured ``attach_to`` target — attach-only providers never provision."""
        attach_to = getattr(self._config, "attach_to", None)
        if not attach_to:
            raise SandboxConfigError(f"{self.__class__.__name__} is attach-only: configure the profile's attach_to with the target to connect to")
        return await self.attach(attach_to, principal=principal, policy=policy)

    async def destroy(self, sandbox_id: str) -> None:
        """No-op — the provider never owns the environment, so there is nothing to dispose."""
        return None
