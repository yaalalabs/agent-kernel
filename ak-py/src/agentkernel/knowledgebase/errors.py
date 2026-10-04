"""Exception hierarchy for the knowledge-base capability.

Every knowledge-base failure is a subclass of :class:`KnowledgeError`. Finding nothing
is NOT an error here — a read that matches no records returns an empty list, and a
malformed document is skipped with a diagnostic. These exceptions signal failures of the
knowledge-base *machinery* only, and the tool surface catches them to return an
actionable string to the agent rather than letting them reach the framework.
"""


class KnowledgeError(Exception):
    """Base class for all knowledge-base capability errors."""


class KnowledgeCapabilityError(KnowledgeError):
    """An operation the backend does not declare in its ``KnowledgeCapabilities``.

    Raised either as ``KnowledgeCapabilityError(subject, operation)`` (e.g. the backend
    name plus the missing operation) or ``KnowledgeCapabilityError(operation)``.

    Deliberately not a ``NotImplementedError``: that would be indistinguishable from an
    unimplemented abstract method, and this is a declaration mismatch the tool boundary
    is expected to catch and explain.
    """

    def __init__(self, *args: str) -> None:
        """Accept ``(subject, operation)`` or ``(operation,)`` and build the message."""
        self.subject: str | None = None
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


class KnowledgePathError(KnowledgeError):
    """A path escaped the store's namespace, or is otherwise unusable as an identity.

    Raised by ``DocumentStore`` implementations and mapped to an agent-facing result by
    ``DocumentKnowledgeBase``; a distinct type so that mapping does not have to catch
    ``ValueError`` and swallow unrelated failures.
    """
