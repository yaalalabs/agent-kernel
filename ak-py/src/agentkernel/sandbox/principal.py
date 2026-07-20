"""Resolution of the identity a sandbox execution runs under.

The resolved ``SandboxPrincipal`` is produced agent-side (it needs ``Session`` context),
travels in the broker request message, and is enforced worker-side where the credentials
live. The default resolver returns the agent's own identity; applications supply their own
via the ``sandbox.principal_resolver`` dotted-path config to map their auth context (e.g. a
token their API layer stored in ``session.nv_cache``) into a principal.
"""

from abc import ABC, abstractmethod

from ..core.base import Agent, Session
from .model import SandboxPrincipal


class PrincipalResolver(ABC):
    """Maps the current session + agent to the identity an execution runs under."""

    @abstractmethod
    async def resolve(self, session: Session, agent: Agent) -> SandboxPrincipal:
        """Return the ``SandboxPrincipal`` for this session/agent."""


class AgentPrincipalResolver(PrincipalResolver):
    """Default resolver: the agent's own identity.

    ``subject`` is the agent name and credentials are empty — executions run under whatever
    identity the provider's own configuration carries (API key, ServiceAccount, IAM role).
    """

    async def resolve(self, session: Session, agent: Agent) -> SandboxPrincipal:
        return SandboxPrincipal(mode="agent", subject=agent.name)
