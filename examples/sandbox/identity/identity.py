"""Application-side identity wiring for the sandbox identity demo.

This is the code an application writes to run sandboxed code under the *end user's*
identity rather than one shared agent identity:

* ``USER_DIRECTORY`` — stands in for your IdP / IAM: it maps a bearer token to a user
  record (user id, an assumable role, groups). A real app validates a JWT/OIDC token here.
* ``IdentitySeedPreHook`` — a ``PreHook`` that runs before the agent. It reads the auth
  token the client sent (delivered as an ``AgentRequestAny`` extra field), rejects requests
  with a missing/invalid token, and on success writes the resolved identity onto the
  session so anything later in the turn — including the sandbox — can see who the caller is.
* ``SessionUserPrincipalResolver`` — the ``PrincipalResolver`` the sandbox calls when it
  needs the execution identity. It reads what the pre-hook stored and returns a user-mode
  ``SandboxPrincipal`` (falling back to the agent identity when no user is present).
"""

from typing import Optional

from agentkernel import Agent, PreHook, Session
from agentkernel.core.model import AgentReply, AgentReplyText, AgentRequest, AgentRequestAny
from agentkernel.sandbox import PrincipalResolver, SandboxPrincipal

# The request field the client puts its bearer token in. Any field the API doesn't itself
# consume arrives to hooks as an AgentRequestAny(name=<field>, content=<value>).
AUTH_TOKEN_FIELD = "auth_token"

# Where the pre-hook stashes the resolved identity for the resolver to read.
USER_IDENTITY_KEY = "user_identity"

# Simulated identity provider / IAM mapping. In a real deployment this is your token
# validation + user lookup (OIDC, an internal directory, an IAM role mapping, ...).
USER_DIRECTORY = {
    "token-alice": {
        "user_id": "alice@example.com",
        "role_arn": "arn:aws:iam::111111111111:role/alice",
        "groups": ["engineering"],
    },
    "token-bob": {
        "user_id": "bob@example.com",
        "role_arn": "arn:aws:iam::111111111111:role/bob",
        "groups": ["analytics"],
    },
}


class IdentitySeedPreHook(PreHook):
    """Authenticates the request and records the caller's identity on the session."""

    async def on_run(
        self, session: Session, agent: Agent, requests: list[AgentRequest]
    ) -> list[AgentRequest] | AgentReply:
        token = None
        remaining: list[AgentRequest] = []
        for req in requests:
            if isinstance(req, AgentRequestAny) and req.name == AUTH_TOKEN_FIELD:
                token = req.content  # consume it — the auth token never reaches the agent
            else:
                remaining.append(req)

        if not token:
            return AgentReplyText(response="Unauthorized: no auth token was provided with the request.")

        identity = USER_DIRECTORY.get(token)
        if identity is None:
            return AgentReplyText(response="Unauthorized: the provided auth token is not valid.")

        # Authenticated: record the identity so the sandbox PrincipalResolver can read it.
        session.get_non_volatile_cache().set(USER_IDENTITY_KEY, identity)
        return remaining

    def name(self) -> str:
        return "IdentitySeedPreHook"


class SessionUserPrincipalResolver(PrincipalResolver):
    """Maps the session-recorded user identity to a user-mode ``SandboxPrincipal``."""

    async def resolve(self, session: Session, agent: Optional[Agent]) -> SandboxPrincipal:
        identity = session.get_non_volatile_cache().get(USER_IDENTITY_KEY) if session is not None else None
        if identity:
            return SandboxPrincipal(
                mode="user",
                subject=identity["user_id"],
                credentials={"role_arn": identity["role_arn"]} if identity.get("role_arn") else {},
                groups=identity.get("groups", []),
            )
        # No authenticated user on this session: run as the agent's own identity.
        return SandboxPrincipal(mode="agent", subject=agent.name if agent is not None else "agent")
