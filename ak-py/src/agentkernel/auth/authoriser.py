"""
Pluggable authorization base class for resource-management routes (conversation
threads, scheduled tasks).

Agent Kernel does not verify identity itself: the end user is assumed to
already have an authentication provider. Subclass Authoriser with the custom
logic needed to validate a Bearer token against that provider and resolve the
subject (user_id).
"""

from abc import ABC, abstractmethod
from typing import Optional

from .handler import AuthValidator


class Authoriser(ABC):
    """
    Base class for resource-management route authorization. The end user supplies
    a subclass and passes it to a management request handler (e.g.
    ThreadRESTRequestHandler). When no Authoriser is configured, the protected
    routes remain open.
    """

    @abstractmethod
    def authorise(self, token: str) -> Optional[str]:
        """
        Validate a Bearer token against the caller's own authentication provider.
        :param token: The Bearer token from the Authorization header.
        :return: The resolved subject (user_id) when the token is valid, or None to reject.
        """
        pass


class AuthValidatorAuthoriser(Authoriser):
    """
    Adapter that lets an existing AuthValidator serve as an Authoriser, so one
    user-supplied validator can protect the global REST routes, WebSocket
    $connect, and the resource-management routes without a second implementation.
    """

    def __init__(self, validator: AuthValidator):
        """
        Initializes the adapter.
        :param validator: The AuthValidator whose validate() result is mapped to an authorise() result.
        """
        self._validator = validator

    def authorise(self, token: str) -> Optional[str]:
        """
        Validate the token via the wrapped AuthValidator.
        :param token: The Bearer token from the Authorization header.
        :return: ValidationResult.subject when the token is valid, or None to reject.
        """
        result = self._validator.validate(token)
        return result.subject if result is not None and result.is_valid else None
