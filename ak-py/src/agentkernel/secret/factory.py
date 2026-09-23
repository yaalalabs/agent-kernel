"""SecretProviderFactory — builds the SecretProvider named by `secret.provider.type`."""

import logging

from ..core.config import _SecretConfig
from ..core.util.factory import AKConfigError, require_extra, resolve_dotted
from .base import SecretProvider

_BUILTIN_SECRET_PROVIDERS = ["env", "aws_ssm"]


class SecretProviderFactory:
    """Creates the SecretProvider named by `secret.provider.type`."""

    _log = logging.getLogger("ak.secret.provider.factory")

    @staticmethod
    def create(config: _SecretConfig) -> SecretProvider:
        """Create the configured provider, delegating to its ``from_config`` seam.

        Takes the `secret` block explicitly rather than reading AKConfig, so a caller that already
        holds the block does not re-read it and a test can build a provider from any _SecretConfig.

        :param config: The `secret` configuration block.
        :return: The configured provider.
        :raises AKConfigError: If the configured type is neither a built-in nor a resolvable dotted
                               path, or if the provider's own settings are unusable.
        """
        provider_type = config.provider.type
        SecretProviderFactory._log.info(f"Building '{provider_type}' secret provider")
        key = provider_type.lower()
        if key == "env":
            from .providers.env import EnvSecretProvider

            return EnvSecretProvider.from_config(config)
        if key == "aws_ssm":
            with require_extra("aws", "secret.provider.type: aws_ssm"):
                from .providers.aws_ssm import AWSSMSecretProvider

            return AWSSMSecretProvider.from_config(config)
        if "." not in provider_type:
            raise AKConfigError(
                f"unknown secret provider type '{provider_type}'; expected one of {_BUILTIN_SECRET_PROVIDERS} "
                "or a dotted path to a SecretProvider subclass"
            )
        return resolve_dotted(provider_type, base=SecretProvider).from_config(config)
