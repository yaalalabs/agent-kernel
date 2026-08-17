"""
Relocation shim: Authoriser lives in agentkernel.auth.authoriser (#629).

Kept so existing imports keep resolving: agentkernel.integration.thread.authoriser.Authoriser,
the package export in integration/thread/__init__.py, and the agentkernel.thread star-export.
"""

from ...auth.authoriser import Authoriser

__all__ = ["Authoriser"]
