"""Exception hierarchy for the sandbox capability.

Every sandbox failure is a subclass of :class:`SandboxError`. A failing *program*
(non-zero exit, uncaught exception in the executed code) is NOT an error here — it
is returned as a :class:`agentkernel.sandbox.model.SandboxResult`. These exceptions
signal failures of the sandbox *machinery* only.
"""


class SandboxError(Exception):
    """Base class for all sandbox capability errors."""


class SandboxConfigError(SandboxError):
    """Unknown profile/type/flavor, or a required config block is missing."""


class SandboxCapabilityError(SandboxError):
    """An operation the selected provider does not declare in its ``SandboxCapabilities``."""


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
