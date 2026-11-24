"""BenchIdentityProvider: accepts only `<user>.<hmac-sha256-hex(secret, user)>` tokens signed with the deployment's secret."""

import hashlib
import hmac

from agentkernel.core import Principal
from agentkernel.identity import AuthenticationError, IdentityProvider, RequestContext
from agentkernel.secret import SecretManager
from pydantic import BaseModel


class BenchIdentityProvider(IdentityProvider):
    name = "bench"
    NAMESPACE = "bench"

    def __init__(self, config: BaseModel, secrets: SecretManager | None = None):
        key = (config.model_extra or {}).get("secret_key", "AK_BENCH_AUTH_SECRET")
        value = (secrets or SecretManager.current()).get(key, default=None)
        if not value:
            raise RuntimeError(f"identity.provider.secret_key '{key}' has no value; the bench provider needs its signing secret")
        self._secret = value.encode("utf-8")

    async def authenticate(self, credential: str, context: RequestContext | None = None) -> Principal:
        user, dot, signature = credential.rpartition(".")
        if not dot or not user or not signature:
            raise AuthenticationError("malformed bench token")
        expected = hmac.new(self._secret, user.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise AuthenticationError("bad bench token signature")
        return Principal(subject=user, kind="user", provider=self.name, namespace=self.NAMESPACE)
