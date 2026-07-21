"""Resolution of the identity a sandbox execution runs under.

The resolved ``SandboxPrincipal`` is produced agent-side (it needs ``Session`` context),
travels in the broker request message, and is enforced worker-side where the credentials
live. The default resolver returns the agent's own identity; applications supply their own
via the ``sandbox.principal_resolver`` dotted-path config to map their auth context (e.g. a
token their API layer stored in ``session.nv_cache``) into a principal.
"""

from abc import ABC, abstractmethod
from typing import Optional

from ..core.base import Agent, Session
from .model import SandboxPrincipal


class PrincipalResolver(ABC):
    """Maps the current session + agent to the identity an execution runs under.

    ``agent`` may be ``None`` when a sandbox operation is driven programmatically rather than
    from within a running agent (no tool context); resolvers must tolerate that.
    """

    @abstractmethod
    async def resolve(self, session: Session, agent: Optional[Agent]) -> SandboxPrincipal:
        """Return the ``SandboxPrincipal`` for this session/agent."""


class AgentPrincipalResolver(PrincipalResolver):
    """Default resolver: the agent's own identity.

    ``subject`` is the agent name (or ``"agent"`` when no agent is in context) and credentials
    are empty — executions run under whatever identity the provider's own configuration carries
    (API key, ServiceAccount, IAM role).
    """

    async def resolve(self, session: Session, agent: Optional[Agent]) -> SandboxPrincipal:
        """Return an agent-mode principal named after the current agent (or ``"agent"``)."""
        return SandboxPrincipal(mode="agent", subject=agent.name if agent is not None else "agent")
