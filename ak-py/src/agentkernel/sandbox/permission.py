"""``SandboxPermissionGuard`` — decides whether a profile's policy permits one operation.

The guard reads only the request (operation, payload, policy), never ``AKConfig`` or provider
capabilities, so a queue-flavor worker enforces exactly the policy the agent side resolved.
"Not permitted" is decided here; "cannot" stays with the handles as ``SandboxCapabilityError``.
It runs authoritatively in ``BrokerWorkerCore``; ``check_operation`` is also the entry point for
an agent-side, defence-in-depth check before submit.
"""

import logging
from typing import Any, Mapping, Optional

from pydantic import BaseModel

from .broker.base import ExecutionRequest
from .errors import SandboxPermissionDeniedError
from .model import SandboxPolicy


class PermissionAuditContext(BaseModel):
    """Who and where, for the denial log line only; never part of the decision."""

    profile: str
    agent: str
    ak_session_id: str
    sandbox_session_id: str


class SandboxPermissionGuard:
    """Decides whether one operation is permitted by its profile's policy. Stateless.

    Each denial writes exactly one WARNING on ``ak.sandbox.broker``; callers never log it again.
    """

    _log = logging.getLogger("ak.sandbox.broker")

    def check(self, request: ExecutionRequest) -> None:
        """Worker entry point: check_operation over the request's own fields."""
        context = PermissionAuditContext(
            profile=request.profile,
            agent=request.agent,
            ak_session_id=request.ak_session_id,
            sandbox_session_id=request.sandbox_session.sandbox_session_id,
        )
        self.check_operation(request.operation, request.payload, request.policy, context)

    def check_operation(self, operation: str, payload: Mapping[str, Any], policy: SandboxPolicy, context: PermissionAuditContext) -> None:
        """Raise SandboxPermissionDeniedError (after one WARNING) when the policy denies the operation."""
        reason = self._denial_reason(operation, payload, policy)
        if reason is None:
            return
        self._log.warning(
            "Sandbox permission denied: operation=%s profile=%s agent=%s ak_session_id=%s sandbox_session_id=%s reason=%s",
            operation,
            context.profile,
            context.agent,
            context.ak_session_id,
            context.sandbox_session_id,
            reason,
        )
        raise SandboxPermissionDeniedError(
            f"profile '{context.profile}' does not permit {operation}: {reason}; "
            "this is a configuration decision, so do not retry it through run_command"
        )

    @staticmethod
    def _denial_reason(operation: str, payload: Mapping[str, Any], policy: SandboxPolicy) -> Optional[str]:
        """The deny rules; None = permitted. Reasons hold only names and the permitted list, never code or specs."""
        if operation == "execute_code" and policy.languages is not None:
            language = payload.get("language", "python")
            if language not in policy.languages:
                return f"language '{language}' is not permitted by the profile (permitted: {policy.languages})"
        if operation == "install_packages":
            if policy.package_install is None:
                return "the profile does not permit package installation"
            ecosystem = payload.get("ecosystem", "python")
            if ecosystem not in policy.package_install.ecosystems:
                return f"ecosystem '{ecosystem}' is not permitted by the profile (permitted: {policy.package_install.ecosystems})"
        return None
