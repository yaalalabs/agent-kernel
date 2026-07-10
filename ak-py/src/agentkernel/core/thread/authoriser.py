"""
Pluggable authorization base class for Conversation Thread Support.

Agent Kernel does not verify identity itself — the end user is assumed to
already have an authentication provider. Subclass Authoriser with the custom
logic needed to validate a Bearer token against that provider and resolve the
subject (user_id).
"""

from abc import ABC, abstractmethod
from typing import Optional


class Authoriser(ABC):
    """
    Base class for thread route authorization. The end user supplies a subclass
    and passes it to ThreadRESTRequestHandler. When no Authoriser is configured,
    thread routes remain open.
    """

    @abstractmethod
    def authorise(self, token: str) -> Optional[str]:
        """
        Validate a Bearer token against the caller's own authentication provider.
        :param token: The Bearer token from the Authorization header.
        :return: The resolved subject (user_id) when the token is valid, or None to reject.
        """
        pass
