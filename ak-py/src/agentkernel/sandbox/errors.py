"""Exception hierarchy for the sandbox capability.

Every sandbox failure is a subclass of :class:`SandboxError`. A failing *program*
(non-zero exit, uncaught exception in the executed code) is NOT an error here — it
is returned as a :class:`agentkernel.sandbox.model.SandboxResult`. These exceptions
signal failures of the sandbox *machinery* only.
"""

from typing import Optional


class SandboxError(Exception):
    """Base class for all sandbox capability errors."""


class SandboxConfigError(SandboxError):
    """Unknown profile/type/flavor, or a required config block is missing."""


class SandboxCapabilityError(SandboxError):
    """An operation the selected provider does not declare in its ``SandboxCapabilities``.

    Raised either as ``SandboxCapabilityError(subject, capability)`` (e.g. the sandbox or
    provider class name plus the missing capability) or ``SandboxCapabilityError(capability)``.
    """

    def __init__(self, *args: str) -> None:
        """Accept ``(subject, capability)`` or ``(capability,)`` and build the message."""
        self.subject: Optional[str] = None
        self.capability: str = ""
        if len(args) == 2:
            self.subject, self.capability = args[0], args[1]
            message = f"{self.subject} does not support capability: {self.capability}"
        elif len(args) == 1:
            self.capability = args[0]
            message = f"unsupported capability: {self.capability}"
        else:
            message = ""
        super().__init__(message)


class SandboxPolicyError(SandboxError):
    """A policy that cannot be enforced (under ``strict``) or has been violated; also the user-identity fail-closed signal."""


class SandboxTimeoutError(SandboxError):
    """The effective execution timeout was exceeded."""


class SandboxProvisionError(SandboxError):
    """Creating or attaching to a sandbox failed."""


class SandboxGoneError(SandboxProvisionError):
    """An attach target no longer exists — the self-heal signal for a stale handle."""


class SandboxSessionNotFoundError(SandboxError):
    """No sandbox session matches the given ``sandbox_session_id``."""


class SandboxBrokerError(SandboxError):
    """A broker transport or delivery failure."""
