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
    """Maps the current session + agent to the identity an execution runs under.

    ``agent`` may be ``None`` when a sandbox operation is driven programmatically rather than
    from within a running agent (no tool context); resolvers must tolerate that.
    """

    @abstractmethod
    async def resolve(self, session: Session, agent: Agent | None) -> SandboxPrincipal:
        """Return the ``SandboxPrincipal`` for this session/agent."""


class AgentPrincipalResolver(PrincipalResolver):
    """Default resolver: the run's principal when the surface authenticated one, else the agent's own identity.

    A run ``Runtime`` published for an authenticated caller (spec #603, section 8.12) resolves to
    a ``user``-mode principal carrying that caller's subject and groups, so a profile with
    ``identity.mode: user`` works with no custom resolver. An anonymous run, or a sandbox operation
    driven outside a run, resolves to ``agent`` mode: ``subject`` is the agent name (or ``"agent"``
    when no agent is in context). Credentials are empty either way: executions run under
    whatever identity the provider's own configuration carries (API key, ServiceAccount, IAM role),
    and a resolver that maps the caller onto provider credentials is the application's to supply.
    """

    async def resolve(self, session: Session, agent: Agent | None) -> SandboxPrincipal:
        """Return the user-mode principal of an authenticated run, else the agent-mode principal."""
        principal = session.get_principal()
        if principal is not None and not principal.is_anonymous:
            return SandboxPrincipal(mode="user", subject=principal.subject, groups=list(principal.groups))
        return SandboxPrincipal(mode="agent", subject=agent.name if agent is not None else "agent")
