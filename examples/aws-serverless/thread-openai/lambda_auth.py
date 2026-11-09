"""Authorizer Lambda: bearer-token auth on every route; the token names the user.

Two layers protect the thread read routes, both in this one authorizer:
- Route rules: the validator gets the request path and method, so it decides who may call which
  route. Here `guest` may chat but may not read threads.
- Principal scoping: the validator's subject becomes the request's `principalId`, and
  LambdaThreadHost limits the read routes to it: a listing is forced to that user, and another
  user's thread answers 403.

DEMO ONLY: a static token map stands in for your identity provider. Replace DemoValidator with a
real token check (e.g. verify a JWT signature) before deploying anything you care about.
"""

from agentkernel.auth import AuthValidator, ValidationContext, ValidationResult
from agentkernel.aws import APIGatewayAuthorizer


class DemoValidator(AuthValidator):
    """Accepts the demo tokens, names their user, and keeps the thread routes from guests."""

    _TOKENS = {
        "alice-token": "alice",
        "bob-token": "bob",
        "guest-token": "guest",
    }
    _THREAD_READERS = {"alice", "bob"}

    def validate(self, token: str, context: ValidationContext | None = None) -> ValidationResult:
        user = self._TOKENS.get(token)
        if user is None:
            return ValidationResult(is_valid=False, subject=None)
        if self._reads_threads(context) and user not in self._THREAD_READERS:
            return ValidationResult(is_valid=False, subject=user, error_msg="not allowed to read threads")
        return ValidationResult(is_valid=True, subject=user)

    @staticmethod
    def _reads_threads(context: ValidationContext | None) -> bool:
        """GET /<base>/<version>/threads[/{session_id}]; an event without a path counts as one (fail closed)."""
        if context is None or not context.path:
            return True
        return context.http_method == "GET" and "threads" in context.path.strip("/").split("/")


handler = APIGatewayAuthorizer(validator=DemoValidator()).handle
