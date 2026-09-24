"""AWSSMSecretProvider — AWS SSM Parameter Store as the managed secret store.

The only component that knows about paths, prefixes or case: the environment-variable-style key
OPENAI_API_KEY becomes the parameter /ak/{prefix}/openai_api_key.
"""

import logging
from threading import Lock
from typing import Any, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from ...core.config import _SecretConfig
from ...core.util.factory import AKConfigError
from ..base import SecretProvider
from ..errors import SecretError

_NOT_FOUND_ERROR_CODE = "ParameterNotFound"


class AWSSMSecretProvider(SecretProvider):
    """AWS SSM Parameter Store, read-only, one call: GetParameter(WithDecryption=True).

    Addressing: the env-style key OPENAI_API_KEY becomes the parameter /ak/{prefix}/openai_api_key.
    The leading slash is required — SSM rejects a hierarchical name without one — and the IAM
    resource ARN parameter/ak/{prefix}/* is the ARN of exactly this name.
    """

    _log = logging.getLogger("ak.secret.provider.aws_ssm")

    def __init__(self, prefix: str) -> None:
        """:raises AKConfigError: If prefix is empty, or still contains '/' after stripping."""
        self._prefix = self._normalize_prefix(prefix)
        self._client: Optional[Any] = None
        self._client_lock = Lock()

    @classmethod
    def from_config(cls, config: _SecretConfig) -> "AWSSMSecretProvider":
        """Build the provider from the `secret` block; reads `secret.prefix` only.

        :raises AKConfigError: If `secret.prefix` is empty or nested.
        """
        return cls(prefix=config.prefix)

    @property
    def client(self) -> Any:
        """Lazily created boto3 SSM client. Region and credentials come from the boto3 environment
        default, matching DynamoDBDriver (core/util/driver/dynamodb.py)."""
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    self._client = boto3.client("ssm")
        return self._client

    def get_secret(self, key: str) -> Optional[str]:
        """Read /ak/{prefix}/{key.lower()}; a missing parameter is a miss, any other failure raises.

        :raises SecretError: If SSM rejected or failed the call for any reason other than
                             ParameterNotFound.
        """
        path = self._compose_path(key)
        try:
            response = self.client.get_parameter(Name=path, WithDecryption=True)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code == _NOT_FOUND_ERROR_CODE:
                self._log.debug("No SSM parameter at %s", path)
                return None
            raise SecretError(f"SSM GetParameter failed for '{path}': {code}") from exc
        except BotoCoreError as exc:
            raise SecretError(f"SSM GetParameter failed for '{path}': {type(exc).__name__}") from exc
        return response["Parameter"]["Value"]

    def _compose_path(self, key: str) -> str:
        return f"/ak/{self._prefix}/{key.lower()}"

    @staticmethod
    def _normalize_prefix(prefix: str) -> str:
        """:raises AKConfigError: If prefix is empty, or contains '/' after stripping leading/trailing."""
        normalized = prefix.strip("/")
        if not normalized:
            raise AKConfigError(
                "secret.provider.type: aws_ssm requires secret.prefix (AK_SECRET__PREFIX) — the deployment scope "
                "secrets are read from, as /ak/{prefix}/<key>"
            )
        if "/" in normalized:
            raise AKConfigError(
                f"secret.prefix '{prefix}' must be a single path segment: a nested prefix would compose outside the "
                "provisioned parameter/ak/{prefix}/* grant"
            )
        return normalized
