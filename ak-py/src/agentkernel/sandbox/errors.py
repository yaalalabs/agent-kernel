"""Exception hierarchy for the sandbox capability.

Every sandbox failure is a subclass of :class:`SandboxError`. A failing *program*
(non-zero exit, uncaught exception in the executed code) is NOT an error here — it
is returned as a :class:`agentkernel.sandbox.model.SandboxResult`. These exceptions
signal failures of the sandbox *machinery* only.
"""

from typing import Optional


class SandboxError(Exception):
    """Base class for all sandbox capability errors."""

    @classmethod
    def from_message(cls, message: str) -> "SandboxError":
        """Rebuild an error from its ``str()``, e.g. a completion's error carried over the wire."""
        return cls(message)


class SandboxConfigError(SandboxError):
    """Unknown profile/type/flavor, or a required config block is missing."""


class SandboxCapabilityError(SandboxError):
    """An operation the selected provider does not declare in its ``SandboxCapabilities``.

    Raised either as ``SandboxCapabilityError(subject, capability)`` (e.g. the sandbox or
    provider class name plus the missing capability) or ``SandboxCapabilityError(capability)``.
    """

    # The two message forms; from_message parses them back.
    _SUBJECT_SEPARATOR = " does not support capability: "
    _BARE_PREFIX = "unsupported capability: "

    def __init__(self, *args: str) -> None:
        """Accept ``(subject, capability)`` or ``(capability,)`` and build the message."""
        self.subject: Optional[str] = None
        self.capability: str = ""
        if len(args) == 2:
            self.subject, self.capability = args[0], args[1]
            message = f"{self.subject}{self._SUBJECT_SEPARATOR}{self.capability}"
        elif len(args) == 1:
            self.capability = args[0]
            message = f"{self._BARE_PREFIX}{self.capability}"
        else:
            message = ""
        super().__init__(message)

    @classmethod
    def from_message(cls, message: str) -> "SandboxCapabilityError":
        """Rebuild from the message either constructor form produces, restoring ``subject`` and
        ``capability``, so the message is not wrapped a second time. Any other text is kept verbatim."""
        subject, separator, capability = message.partition(cls._SUBJECT_SEPARATOR)
        if separator:
            return cls(subject, capability)
        if message.startswith(cls._BARE_PREFIX):
            return cls(message[len(cls._BARE_PREFIX) :])
        exc = cls()
        exc.args = (message,)
        return exc


class SandboxPolicyError(SandboxError):
    """A policy that cannot be enforced (under ``strict``) or has been violated; also the user-identity fail-closed signal."""


class SandboxPermissionDeniedError(SandboxPolicyError):
    """The profile's policy does not permit this operation (raised and audit-logged by SandboxPermissionGuard)."""


class SandboxTimeoutError(SandboxError):
    """The effective execution timeout was exceeded."""


class SandboxProvisionError(SandboxError):
    """Creating or attaching to a sandbox failed."""


class SandboxGoneError(SandboxProvisionError):
    """An attach target no longer exists — the self-heal signal for a stale handle."""


class SandboxSessionNotFoundError(SandboxError):
    """No sandbox session matches the given ``sandbox_session_id``."""


class ExecutionBrokerError(SandboxError):
    """A broker transport or delivery failure."""
